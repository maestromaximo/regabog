from django.urls import path
from . import views

app_name = 'lawyer'

urlpatterns = [
    path('', views.home, name='home'),
    path('chat/', views.chat, name='chat'),
    path('configure/', views.configure, name='configure'),
    path('upload/', views.upload_documents, name='upload_documents'),
    path('case/create/', views.create_case, name='create_case'),
    path('document/<int:document_id>/delete/', views.delete_document, name='delete_document'),
    path('chat/send/', views.send_message, name='send_message'),
    path('chat/<int:conversation_id>/', views.get_conversation, name='get_conversation'),
    path('chat/new/', views.new_conversation, name='new_conversation'),
] 