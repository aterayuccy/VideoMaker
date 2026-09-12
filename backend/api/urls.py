from django.urls import path
from . import views

urlpatterns=[
    path("tts/voices/",views.tts_voices,name="tts-voices"),
    path("tts/",views.text_to_speech,name="text-to-speech"),
    path("pixabay/video/",views.search_pixabay_video,name="search-pixabay-video"),
    path("video/compose/",views.compose_video,name="compose-video"),
]
