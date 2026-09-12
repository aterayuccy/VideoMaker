from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class Note(models.Model):
    title=models.CharField(max_length=100)
    content=models.TextField()
    created_at=models.DateTimeField(auto_now_add=True)
    author=models.ForeignKey(User,on_delete=models.CASCADE,related_name='notes', null=True)

    workspace_id = models.UUIDField(null=True, db_index=True, editable=False)

    def __str__(self):
        return self.title


class SavedVideo(models.Model):
    class VideoFormat(models.TextChoices):
        SHORT = "short", "短影片"
        LONG = "long", "長影片"

    title = models.CharField(max_length=120)
    video = models.FileField(upload_to="saved_videos/")
    video_format = models.CharField(
        max_length=10,
        choices=VideoFormat.choices,
        default=VideoFormat.LONG,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_videos", null=True)

    def delete(self, *args, **kwargs):
        storage = self.video.storage
        name = self.video.name
        super().delete(*args, **kwargs)

        if name and storage.exists(name):
            storage.delete(name)

    workspace_id = models.UUIDField(null=True, db_index=True, editable=False)

    def __str__(self):
        return self.title
