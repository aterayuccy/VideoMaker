from uuid import uuid4
from tempfile import TemporaryDirectory
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient


class WorkspaceTests(TestCase):
    def test_saved_work_is_accessible_without_login_and_isolated(self):
        owner, other = APIClient(), APIClient()
        owner.credentials(HTTP_X_WORKSPACE_ID=str(uuid4()))
        other.credentials(HTTP_X_WORKSPACE_ID=str(uuid4()))
        with TemporaryDirectory() as root, self.settings(MEDIA_ROOT=root):
            created = owner.post('/api/videos/', {
                'title': 'Guest video',
                'video': SimpleUploadedFile('clip.mp4', b'video', content_type='video/mp4'),
            }, format='multipart')
            self.assertEqual(created.status_code, 201)
            pk = created.data['id']
            self.assertEqual(len(owner.get('/api/videos/').data), 1)
            self.assertEqual(other.get('/api/videos/').data, [])
            self.assertEqual(other.delete(f'/api/videos/delete/{pk}/').status_code, 404)
            self.assertEqual(owner.delete(f'/api/videos/delete/{pk}/').status_code, 204)

    def test_missing_or_invalid_workspace_cannot_list_work(self):
        client = APIClient()
        self.assertEqual(client.get('/api/videos/').status_code, 400)
        client.credentials(HTTP_X_WORKSPACE_ID='invalid')
        self.assertEqual(client.get('/api/videos/').status_code, 400)

    def test_account_endpoints_removed(self):
        for url in ['/api/user/register/', '/api/user/me/', '/api/token/', '/api/token/refresh/']:
            self.assertEqual(self.client.post(url).status_code, 404)

    def test_voices_available_without_login(self):
        self.assertEqual(self.client.get('/api/tts/voices/').status_code, 200)
