from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from .services import get_openai_client, extract_text_from_pdf
import os

class BaseDocument(models.Model):
    filename = models.CharField(max_length=255)
    filepath = models.CharField(max_length=1000, blank=True, null=True)
    file = models.FileField(upload_to='documents/', blank=True, null=True)
    resource_link = models.URLField(max_length=1000, blank=True, null=True)
    contents = models.TextField(blank=True, null=True)  # New field for storing document contents
    description = models.TextField(blank=True, null=True)
    embeddings = models.JSONField(blank=True, null=True)  # Store vector embeddings as JSON
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='documents')

    def __str__(self):
        return self.filename

    def save(self, *args, **kwargs):
        # Try to read and save file contents if a file is present
        if self.file and not self.contents:
            try:
                # Read file contents based on file type
                file_content = ""
                if self.filename.lower().endswith('.txt'):
                    file_content = self.file.read().decode('utf-8')
                elif self.filename.lower().endswith('.pdf'):
                    # PDF handling is in services.py
                    file_content = extract_text_from_pdf(self.file)
                
                self.contents = file_content
            except Exception as e:
                print(f"Error reading file contents: {str(e)}")

        # Generate description and embeddings using OpenAI if we have contents
        if self.contents and (not self.description or not self.embeddings):
            try:
                client = get_openai_client()
                
                # Generate description using OpenAI
                prompt = f"Given the following legal document, summarize in a single to three paragraphs the contents of the document, capture all the necessary aspects, the title is {self.filename} and the content is: {self.contents[:4000]}"  # Limit content length
                
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a legal document summarizer. Provide concise, accurate summaries capturing key legal aspects."},
                        {"role": "user", "content": prompt}
                    ]
                )
                
                self.description = response.choices[0].message.content

                # Generate embeddings for the description
                embedding_response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=self.description,
                    encoding_format="float"
                )
                
                self.embeddings = embedding_response.data[0].embedding

            except Exception as e:
                print(f"Error generating description or embeddings: {str(e)}")

        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']

class Case(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('archived', 'Archived')
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cases')
    documents = models.ManyToManyField(BaseDocument, related_name='cases', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tags = models.JSONField(blank=True, null=True)  # Store case tags as JSON

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-created_at']


class FlowCase(models.Model):
    """The main idea is to have a special case, that is used to store a spceial but separate type of case
    the idea is that it will first recieve a case then it will have additional fields called objective, which is not optional
    that is the field that states what objective we want with the case. Then in addition,
    we will have your conclusion fields, these are issues, facts, avenues (like possible defenses, etc), and then the
    final field is the conclusion, which is the final answer to the objective.
    """

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name='flow_cases')
    objective = models.TextField(blank=True, null=True)
    issues = models.TextField(blank=True, null=True)
    facts = models.TextField(blank=True, null=True)
    avenues = models.TextField(blank=True, null=True)
    conclusion = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    is_completed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.case.title} - {self.objective}"
    

class Conversation(models.Model):
    title = models.CharField(max_length=255)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name='conversations')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    context = models.JSONField(blank=True, null=True)  # Store conversation context/memory as JSON

    def __str__(self):
        return f"{self.title} - {self.case.title}"

    class Meta:
        ordering = ['-updated_at']

class Message(models.Model):
    MESSAGE_TYPES = [
        ('user', 'User Message'),
        ('assistant', 'Assistant Message'),
        ('system', 'System Message')
    ]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(blank=True, null=True)  # Store additional message metadata as JSON
    referenced_documents = models.ManyToManyField(BaseDocument, related_name='referenced_in_messages', blank=True)

    def __str__(self):
        return f"{self.message_type}: {self.content[:50]}..."

    class Meta:
        ordering = ['created_at']
