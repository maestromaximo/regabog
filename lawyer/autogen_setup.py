import autogen
from typing import List, Dict, Any, Optional
import os
from django.contrib.auth.models import User
from django.conf import settings
from .utils import (
    create_case_with_title,
    get_case_by_id,
    get_user_cases,
    add_documents_to_case,
    update_case_status,
    get_case_documents,
    search_documents_by_similarity,
    search_documents_by_text,
    get_case_summary,
    find_similar_cases
)

def get_agent_config():
    """Get the base configuration for GPT-3.5"""
    api_key = settings.OPENAI_API_KEY
    print(f"API Key length: {len(api_key) if api_key else 0}")
    print(f"API Key starts with: {api_key[:10] if api_key else 'None'}")
    
    if not api_key:
        raise ValueError("OpenAI API key not found in Django settings")
    
    return {
        "temperature": 0.5,
        "config_list": [{
            "model": "gpt-4o",
            "api_key": api_key
        }],
    }

def create_agents(user: User):
    """Create and return all necessary agents with registered tools"""
    config = get_agent_config()
    
    # Create wrapper functions that don't expose User model
    def wrapped_create_case(title: str, description: str = "") -> Dict[str, Any]:
        case = create_case_with_title(title=title, description=description, user=user)
        return {"id": str(case.id), "title": str(case.title), "description": str(case.description)}
    
    def wrapped_get_case(case_id: int) -> Optional[Dict[str, Any]]:
        case = get_case_by_id(case_id=case_id, user=user)
        if not case:
            return None
        return {"id": str(case.id), "title": str(case.title)}
    
    def wrapped_get_cases(status: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        cases = get_user_cases(user=user, status=status, limit=limit)
        return [{"id": str(case.id), "title": str(case.title)} for case in cases]
    
    def wrapped_search_similar_cases(query: str, limit: int = 5) -> List[Dict[str, Any]]:
        results = find_similar_cases(query=query, user=user, limit=limit)
        return [{
            "case": {"id": str(r["case"].id), "title": str(r["case"].title)}, 
            "similarity": float(r["similarity"])
        } for r in results]
    
    def wrapped_search_documents(query: str, limit: int = 5) -> List[Dict[str, Any]]:
        results = search_documents_by_similarity(query=query, user=user, limit=limit)
        return [{
            "id": str(doc.id),
            "filename": str(doc.filename),
            "description": str(doc.description),
            "similarity": float(score)
        } for doc, score in results]
    
    def wrapped_get_case_documents(case_id: int) -> List[Dict[str, Any]]:
        documents = get_case_documents(case_id=case_id, user=user)
        return [{
            "id": str(doc.id),
            "filename": str(doc.filename),
            "description": str(doc.description)
        } for doc in documents]
    
    def wrapped_get_case_summary(case_id: int) -> Dict[str, Any]:
        summary = get_case_summary(case_id=case_id, user=user)
        return {
            "id": str(summary["case"].id),
            "title": str(summary["case"].title),
            "description": str(summary["case"].description),
            "document_count": int(summary["document_count"]),
            "status": str(summary["status"])
        }

    # Create agents with the same system messages
    user_proxy = autogen.UserProxyAgent(
        name="Lawyer",
        system_message="""You are the primary interface for human legal professionals...""",
        code_execution_config=False,
        human_input_mode="NEVER"
    )
    
    planner = autogen.AssistantAgent(
        name="Planner",
        llm_config=config,
        system_message="""You are the Planner, the orchestrator of tasks..."""
    )
    
    legal_expert = autogen.AssistantAgent(
        name="LegalExpert",
        llm_config=config,
        system_message="""You are the LegalExpert, specializing in legal analysis..."""
    )
    
    critic = autogen.AssistantAgent(
        name="Critic",
        llm_config=config,
        system_message="""You are the Critic, ensuring quality and accuracy..."""
    )

    # Register wrapped functions for user_proxy
    function_map = {
        "create_case": wrapped_create_case,
        "get_case": wrapped_get_case,
        "get_cases": wrapped_get_cases,
        "search_similar_cases": wrapped_search_similar_cases,
        "search_documents": wrapped_search_documents,
        "get_case_documents": wrapped_get_case_documents,
        "get_case_summary": wrapped_get_case_summary,
    }

    for name, func in function_map.items():
        user_proxy.register_for_execution(name)(func)

    # Register functions with other agents
    for agent in [planner, legal_expert, critic]:
        for name, func in function_map.items():
            agent.register_for_llm(
                name=name,
                description=func.__doc__ or f"Execute {name}"
            )(func)

    return {
        "user_proxy": user_proxy,
        "planner": planner,
        "legal_expert": legal_expert,
        "critic": critic
    }

def create_group_chat(agents: Dict[str, Any]):
    """Create a group chat with the given agents"""
    # Define allowed transitions
    allowed_transitions = {
        agents["user_proxy"]: [agents["planner"]],
        agents["planner"]: [agents["legal_expert"], agents["critic"]],
        agents["legal_expert"]: [agents["planner"]],
        agents["critic"]: [agents["planner"]]
    }

    # Create group chat with controlled flow
    group_chat = autogen.GroupChat(
        agents=list(agents.values()),
        messages=[],
        max_round=20,
        allowed_or_disallowed_speaker_transitions=allowed_transitions,
        speaker_transitions_type="allowed",
        send_introductions=True
    )
    
    return autogen.GroupChatManager(
        groupchat=group_chat,
        llm_config=get_agent_config(),
    )