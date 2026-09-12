from django.urls import path
from . import views

urlpatterns=[
    path("notes/",views.NoteListCreate.as_view(),name="note-list"),
    path("notes/delete/<int:pk>/",views.NoteDelete.as_view(),name="delete-note"),
    path("tts/voices/",views.tts_voices,name="tts-voices"),
    path("tts/",views.text_to_speech,name="text-to-speech"),
    path("pixabay/video/",views.search_pixabay_video,name="search-pixabay-video"),
    path("builtin-materials/",views.upload_builtin_material,name="upload-builtin-material"),
    path("video/compose/",views.compose_video,name="compose-video"),
]
