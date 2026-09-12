from django.urls import path,include
from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.urls import re_path
from django.views.static import serve as serve_media
urlpatterns = [
    path("api/health/", lambda request: JsonResponse({"status": "ok"}), name="health"),
    path("api/",include("api.urls"))
]

urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve_media, {"document_root": settings.MEDIA_ROOT}),
]


def frontend(request):
    index_path = settings.FRONTEND_DIST / "index.html"
    if not index_path.exists():
        return JsonResponse({"detail": "Frontend build is not installed."}, status=404)
    return FileResponse(index_path.open("rb"), content_type="text/html")


urlpatterns += [
    path("", frontend, name="frontend"),
    re_path(r"^(?!api/|admin/|media/|static/).*$", frontend, name="frontend-fallback"),
]
