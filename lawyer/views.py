from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
from django.views.decorators.csrf import csrf_exempt
from .forms import CaseForm
from .utils import (
    process_multiple_documents,
    create_case_with_title,
    add_documents_to_case
)
from .models import BaseDocument, Case, Conversation, Message
from .autogen_setup import create_agents, create_group_chat
from .services import get_openai_client
import json

def home(request):
    return render(request, 'home.html')

@login_required
def chat(request):
    # Get or create a default case for the user
    default_case, created = Case.objects.get_or_create(
        title="Default Case",
        created_by=request.user,
        defaults={'description': 'Default case for general conversations'}
    )
    
    # Get all conversations for the user
    conversations = Conversation.objects.filter(
        created_by=request.user
    ).order_by('-updated_at')
    
    # Get current conversation or create new one
    current_conversation = conversations.first()
    if not current_conversation:
        from django.utils import timezone
        current_time = timezone.now().strftime("%b %d, %Y %I:%M %p")
        current_conversation = Conversation.objects.create(
            title=f"Legal Consultation - {current_time}",
            case=default_case,
            created_by=request.user,
            is_active=True
        )
    
    # Get conversation history
    messages = Message.objects.filter(conversation=current_conversation).order_by('created_at')
    
    context = {
        'current_conversation': current_conversation,
        'conversations': conversations,
        'messages': messages
    }
    return render(request, 'chat.html', context)

@login_required
def configure(request):
    case_form = CaseForm()
    
    # Get user's documents
    documents = BaseDocument.objects.filter(uploaded_by=request.user).order_by('-created_at')
    
    context = {
        'case_form': case_form,
        'documents': documents
    }
    return render(request, 'configure.html', context)

@login_required
@csrf_exempt  # Temporary for testing
@require_http_methods(["POST"])
def upload_documents(request):
    try:
        files = request.FILES.getlist('files[]')
        if not files:
            return JsonResponse({
                'status': 'error',
                'message': 'No files were uploaded.'
            }, status=400)

        # Process the uploaded files
        result = process_multiple_documents(
            files=files,
            user=request.user
        )

        # Prepare response
        response_data = {
            'status': 'success',
            'message': f"Successfully processed {len(result['success'])} documents",
            'documents': [{
                'id': doc.id,
                'filename': doc.filename,
                'created_at': doc.created_at.isoformat(),
                'description': doc.description
            } for doc in result['success']],
            'errors': result['errors']
        }

        # If there were any errors, change status to partial success
        if result['errors']:
            response_data['status'] = 'partial_success'
            response_data['message'] += f" with {len(result['errors'])} errors"

        return JsonResponse(response_data)

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
@csrf_exempt  # Temporary for testing
@require_http_methods(["POST"])
def create_case(request):
    try:
        data = json.loads(request.body)
        title = data.get('title')
        description = data.get('description', '')
        document_ids = data.get('document_ids', [])

        if not title:
            raise ValidationError('Title is required')

        # Get the selected documents
        documents = BaseDocument.objects.filter(
            id__in=document_ids,
            uploaded_by=request.user
        )

        # Create the case
        case = create_case_with_title(
            title=title,
            description=description,
            user=request.user
        )
        
        # Add documents if any
        if documents:
            add_documents_to_case(case, documents)

        return JsonResponse({
            'status': 'success',
            'message': 'Case created successfully',
            'case': {
                'id': case.id,
                'title': case.title,
                'description': case.description,
                'document_count': documents.count()
            }
        })

    except ValidationError as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
@csrf_exempt  # Temporary for testing
@require_http_methods(["DELETE"])
def delete_document(request, document_id):
    try:
        document = BaseDocument.objects.get(id=document_id, uploaded_by=request.user)
        document.delete()
        return JsonResponse({
            'status': 'success',
            'message': 'Document deleted successfully'
        })
    except BaseDocument.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Document not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def send_message(request):
    try:
        data = json.loads(request.body)
        conversation_id = data.get('conversation_id')
        content = data.get('message')
        
        if not content:
            return JsonResponse({
                'status': 'error',
                'message': 'Message content is required'
            }, status=400)

        conversation = Conversation.objects.get(id=conversation_id, created_by=request.user)
        
        # Save user message
        user_message = Message.objects.create(
            conversation=conversation,
            message_type='user',
            content=content
        )

        # Create agents with tools
        agents = create_agents(request.user)
        manager = create_group_chat(agents)
        
        # Start the conversation with the user's message
        response = agents["user_proxy"].initiate_chat(
            manager,
            message=content,
            clear_history=True
        )

        # Process and save agent messages
        agent_messages = []
        final_response = None
        referenced_docs = set()
        
        # Get all messages from the group chat
        all_messages = manager.groupchat.messages
        
        for msg in all_messages:
            if msg["role"] != "user":  # Skip user messages
                agent_message = {
                    "role": msg["role"],
                    "sender": msg.get("name", "System"),
                    "content": msg["content"]
                }
                agent_messages.append(agent_message)
                
                # Save to database
                if msg.get("name") == "LegalExpert":
                    message_type = 'assistant'
                    final_response = msg["content"]
                else:
                    message_type = 'system'
                
                # Create message and track referenced documents
                message = Message.objects.create(
                    conversation=conversation,
                    message_type=message_type,
                    content=msg["content"],
                    metadata={"sender": msg.get("name", "System"), "role": msg["role"]}
                )

                # If message contains document references, add them
                if "metadata" in msg and "documents" in msg["metadata"]:
                    doc_ids = msg["metadata"]["documents"]
                    docs = BaseDocument.objects.filter(id__in=doc_ids)
                    message.referenced_documents.add(*docs)
                    referenced_docs.update(docs)

        # If no LegalExpert response was found, use the last non-user message
        if final_response is None and agent_messages:
            final_response = agent_messages[-1]["content"]

        return JsonResponse({
            'status': 'success',
            'response': {
                'content': final_response,
                'agent_messages': agent_messages,
                'referenced_documents': [{
                    'id': doc.id,
                    'filename': doc.filename,
                    'description': doc.description
                } for doc in referenced_docs]
            }
        })

    except Exception as e:
        import traceback
        print(f"Error in send_message: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def get_conversation(request, conversation_id):
    try:
        conversation = Conversation.objects.get(
            id=conversation_id,
            created_by=request.user
        )
        messages = Message.objects.filter(conversation=conversation).order_by('created_at')
        
        return JsonResponse({
            'status': 'success',
            'messages': [{
                'content': msg.content,
                'message_type': msg.message_type,
                'created_at': msg.created_at.isoformat()
            } for msg in messages]
        })
    except Conversation.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Conversation not found'
        }, status=404)

@login_required
@require_http_methods(["POST"])
def new_conversation(request):
    try:
        default_case = Case.objects.get(
            title="Default Case",
            created_by=request.user
        )
        
        conversation = Conversation.objects.create(
            title=f"New Conversation {Conversation.objects.count() + 1}",
            case=default_case,
            created_by=request.user,
            is_active=True
        )
        
        return JsonResponse({
            'status': 'success',
            'conversation': {
                'id': conversation.id,
                'title': conversation.title
            }
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)
