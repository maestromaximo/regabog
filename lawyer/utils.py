import os
from typing import List, Dict, Any, Optional
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from openai import OpenAI
from tqdm import tqdm
import json
import numpy as np
from .models import BaseDocument, Case
from django.contrib.auth.models import User
from django.db.models import Q
from .services import get_openai_client, extract_text_from_pdf

def get_embeddings(text: str, client: OpenAI) -> List[float]:
    """Get embeddings for text using OpenAI's API"""
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
            encoding_format="float"
        )
        return response.data[0].embedding
    except Exception as e:
        raise Exception(f"Error getting embeddings: {str(e)}")

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculate cosine similarity between two vectors"""
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

# Case Management Functions
def create_case_with_title(title: str, user: User, description: str = "", documents: List[BaseDocument] = None) -> Case:
    """Create a new case with given title and optional description and documents"""
    case = Case.objects.create(
        title=title,
        description=description,
        created_by=user,
        status='active'
    )
    if documents:
        case.documents.add(*documents)
    return case

def get_case_by_id(case_id: int, user: User) -> Optional[Case]:
    """Retrieve a case by ID for a specific user"""
    try:
        return Case.objects.get(id=case_id, created_by=user)
    except Case.DoesNotExist:
        return None

def get_user_cases(user: User, status: str = None, limit: int = 10) -> List[Case]:
    """Get cases for a user with optional status filter"""
    query = Q(created_by=user)
    if status:
        query &= Q(status=status)
    return Case.objects.filter(query).order_by('-created_at')[:limit]

def add_documents_to_case(case: Case, documents: List[BaseDocument]) -> Case:
    """Add documents to an existing case"""
    case.documents.add(*documents)
    return case

def update_case_status(case: Case, new_status: str) -> Case:
    """Update the status of a case"""
    if new_status in [status[0] for status in Case.STATUS_CHOICES]:
        case.status = new_status
        case.save()
    return case

def get_case_documents(case: Case) -> List[BaseDocument]:
    """Get all documents associated with a case"""
    return list(case.documents.all().order_by('-created_at'))

# Document Search Functions
def search_documents_by_similarity(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search for documents using cosine similarity with query embeddings"""
    try:
        client = get_openai_client()
        query_embedding = get_embeddings(query, client)
        
        # Get all documents with embeddings
        documents = BaseDocument.objects.exclude(embeddings__isnull=True)
        
        # Calculate similarities
        similarities = []
        for doc in documents:
            if doc.embeddings:  # Make sure document has embeddings
                similarity = cosine_similarity(query_embedding, doc.embeddings)
                similarities.append({
                    'document': doc,
                    'similarity': similarity
                })
        
        # Sort by similarity and get top results
        similarities.sort(key=lambda x: x['similarity'], reverse=True)
        return similarities[:limit]
    
    except Exception as e:
        print(f"Error in similarity search: {str(e)}")
        return []

def search_documents_by_text(query: str, limit: int = 10) -> List[BaseDocument]:
    """Search for documents by text content or description"""
    return BaseDocument.objects.filter(
        Q(contents__icontains=query) |
        Q(description__icontains=query) |
        Q(filename__icontains=query)
    ).distinct()[:limit]

def get_case_summary(case: Case) -> Dict[str, Any]:
    """Get a comprehensive summary of a case including documents and metadata"""
    return {
        'id': case.id,
        'title': case.title,
        'description': case.description,
        'status': case.status,
        'created_at': case.created_at,
        'updated_at': case.updated_at,
        'document_count': case.documents.count(),
        'documents': [{
            'id': doc.id,
            'filename': doc.filename,
            'description': doc.description,
            'created_at': doc.created_at
        } for doc in case.documents.all()],
        'tags': case.tags or []
    }

def find_similar_cases(query: str, user: User, limit: int = 5) -> List[Dict[str, Any]]:
    """Find cases similar to a query using document similarity"""
    try:
        client = get_openai_client()
        query_embedding = get_embeddings(query, client)
        
        # Get all user's cases with their documents
        cases = Case.objects.filter(created_by=user)
        case_similarities = []
        
        for case in cases:
            # Get average similarity across all case documents
            doc_similarities = []
            for doc in case.documents.all():
                if doc.embeddings:
                    similarity = cosine_similarity(query_embedding, doc.embeddings)
                    doc_similarities.append(similarity)
            
            if doc_similarities:
                avg_similarity = sum(doc_similarities) / len(doc_similarities)
                case_similarities.append({
                    'case': case,
                    'similarity': avg_similarity
                })
        
        # Sort by similarity and return top results
        case_similarities.sort(key=lambda x: x['similarity'], reverse=True)
        return case_similarities[:limit]
    
    except Exception as e:
        print(f"Error finding similar cases: {str(e)}")
        return []

# Document Processing Functions
def process_document(file, user: User, client: OpenAI) -> BaseDocument:
    """Process a single document: save file and let the model handle content extraction and OpenAI processing"""
    try:
        document = BaseDocument.objects.create(
            filename=file.name,
            file=file,
            uploaded_by=user
        )
        return document
    except Exception as e:
        raise Exception(f"Error processing document {file.name}: {str(e)}")

def process_multiple_documents(files: List[Any], user: User) -> Dict[str, Any]:
    """Process multiple documents and return results with any errors"""
    client = get_openai_client()
    processed_documents = []
    errors = []

    for file in tqdm(files, desc="Processing documents"):
        try:
            if not file.name.lower().endswith('.pdf'):
                raise ValueError("Only PDF files are supported")
            document = process_document(file, user, client)
            processed_documents.append(document)
        except Exception as e:
            errors.append({"file": file.name, "error": str(e)})

    return {
        "success": processed_documents,
        "errors": errors
    } 