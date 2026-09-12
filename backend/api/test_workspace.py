from django.test import TestCase


class WorkspaceTests(TestCase):
    def test_saved_video_endpoints_removed(self):
        self.assertEqual(self.client.get('/api/videos/').status_code, 404)
        self.assertEqual(self.client.post('/api/videos/').status_code, 404)
        self.assertEqual(self.client.delete('/api/videos/delete/1/').status_code, 404)

    def test_account_endpoints_removed(self):
        for url in ['/api/user/register/', '/api/user/me/', '/api/token/', '/api/token/refresh/']:
            self.assertEqual(self.client.post(url).status_code, 404)

    def test_voices_available_without_login(self):
        self.assertEqual(self.client.get('/api/tts/voices/').status_code, 200)
