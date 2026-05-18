import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crawler


class CrawlerDbMappingTest(unittest.TestCase):
    def test_build_post_row_maps_softcon_details_to_posts_schema(self):
        details = {
            "uid": "123",
            "term": "2024-1",
            "title": "테스트 작품",
            "summary": "작품 요약",
            "description": "짧은 설명",
            "gitRepository": "https://github.com/example/project",
            "presentationUrl": "https://softcon.ajou.ac.kr/files/demo.pdf",
            "videoUrl": "https://youtu.be/demo",
            "representativeImage": "https://softcon.ajou.ac.kr/img/demo.png",
            "url": "https://softcon.ajou.ac.kr/works/works.asp?uid=123",
            "teamInfo": {"members": [{"name": "홍길동"}]},
        }

        row = crawler.build_post_row(details, crawler_user_id=7)

        self.assertEqual(row["user_id"], 7)
        self.assertEqual(row["board_type"], "CRAWLED_PROJECT")
        self.assertEqual(row["title"], "테스트 작품")
        self.assertEqual(row["description"], "짧은 설명")
        self.assertEqual(row["thumbnail_image"], "https://softcon.ajou.ac.kr/img/demo.png")
        self.assertEqual(row["thumbnail_storage_key"], "softcon:2024-1:123")
        self.assertEqual(row["video_link"], "https://youtu.be/demo")
        self.assertEqual(row["github_link"], "https://github.com/example/project")
        self.assertEqual(row["visibility"], "PUBLIC")
        self.assertIn("작품 개요: 작품 요약", row["content"])
        self.assertIn("소프트콘 UID: 123", row["content"])

    def test_db_config_is_optional_when_no_db_env_exists(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(crawler.get_optional_db_config())

    def test_cloud_sql_connection_name_builds_unix_socket_config(self):
        env = {
            "CLOUD_SQL_CONNECTION_NAME": "project:region:instance",
            "DB_USER": "app_user",
            "DB_PASSWORD": "secret",
            "DB_NAME": "aim",
            "CRAWLER_USER_ID": "3",
        }

        with patch.dict(os.environ, env, clear=True):
            config = crawler.get_optional_db_config()

        self.assertEqual(config["unix_socket"], "/cloudsql/project:region:instance")
        self.assertEqual(config["crawler_user_id"], 3)
        self.assertEqual(config["post_table"], "POSTS")

    def test_db_post_table_rejects_unsafe_identifier(self):
        env = {
            "DB_HOST": "127.0.0.1",
            "DB_USER": "app_user",
            "DB_PASSWORD": "secret",
            "DB_NAME": "aim",
            "CRAWLER_USER_ID": "3",
            "DB_POST_TABLE": "POSTS;DROP",
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                crawler.get_optional_db_config()


if __name__ == "__main__":
    unittest.main()
