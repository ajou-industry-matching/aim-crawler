import os
import unittest
from unittest.mock import MagicMock, patch

import crawler


class CrawlerDbConfigTest(unittest.TestCase):
    def test_no_db_env_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(crawler.get_optional_db_config())

    def test_oracle_mysql_tcp_config(self):
        env = {
            "DB_HOST": "161.33.46.41",
            "DB_PORT": "3306",
            "DB_USER": "aim_be",
            "DB_PASSWORD": "dummy",
            "DB_NAME": "aim",
            "CRAWLER_USER_ID": "1",
            "DB_POST_TABLE": "posts",
        }
        with patch.dict(os.environ, env, clear=True):
            config = crawler.get_optional_db_config()

        self.assertEqual(config["host"], "161.33.46.41")
        self.assertEqual(config["port"], 3306)
        self.assertEqual(config["user"], "aim_be")
        self.assertEqual(config["database"], "aim")
        self.assertEqual(config["crawler_user_id"], 1)
        self.assertEqual(config["post_table"], "posts")
        self.assertEqual(config["user_table"], "users")

    def test_allows_auto_creating_crawler_user_without_id(self):
        env = {
            "DB_HOST": "161.33.46.41",
            "DB_USER": "aim_be",
            "DB_PASSWORD": "dummy",
            "DB_NAME": "aim",
            "DB_AUTO_CREATE_CRAWLER_USER": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            config = crawler.get_optional_db_config()

        self.assertIsNone(config["crawler_user_id"])
        self.assertTrue(config["auto_create_crawler_user"])
        self.assertEqual(config["post_table"], "posts")

    def test_rejects_unsafe_table_name(self):
        env = {
            "DB_HOST": "161.33.46.41",
            "DB_USER": "aim_be",
            "DB_PASSWORD": "dummy",
            "DB_NAME": "aim",
            "CRAWLER_USER_ID": "1",
            "DB_POST_TABLE": "POSTS;DROP",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                crawler.get_optional_db_config()

    def test_build_post_row_maps_softcon_project_to_post(self):
        details = {
            "uid": "123",
            "term": "2024-1",
            "title": "작품명",
            "summary": "요약",
            "description": "설명",
            "representativeImage": "https://example.com/image.jpg",
            "videoUrl": "https://example.com/video",
            "gitRepository": "https://github.com/example/repo",
        }

        row = crawler.build_post_row(details, crawler_user_id=1)

        self.assertEqual(row["user_id"], 1)
        self.assertEqual(row["board_type"], "CRAWLED_PROJECT")
        self.assertEqual(row["title"], "작품명")
        self.assertEqual(row["description"], "설명")
        self.assertEqual(row["thumbnail_storage_key"], "softcon:2024-1:123")
        self.assertEqual(row["visibility"], "PUBLIC")

    def test_auto_created_crawler_user_uses_string_admin_role(self):
        # 백엔드 AdminRole enum이 문자열(NONE/ADMIN/SUPER_ADMIN)이므로
        # 자동 생성 유저의 admin_role도 정수가 아닌 문자열 "NONE"으로 들어가야 한다.
        cursor = MagicMock()
        cursor.fetchone.return_value = None  # 기존 크롤러 유저 없음 → INSERT 경로
        cursor.lastrowid = 99
        config = {
            "crawler_user_id": None,
            "user_table": "users",
            "auto_create_crawler_user": True,
            "crawler_user_firebase_uid": "softcon-crawler",
            "crawler_user_email": "softcon-crawler@aim.local",
            "crawler_user_name": "Softcon Crawler",
        }

        user_id = crawler.resolve_crawler_user_id(cursor, config)

        self.assertEqual(user_id, 99)
        insert_call = cursor.execute.call_args_list[-1]
        insert_params = insert_call.args[1]
        self.assertEqual(insert_params[0], "NONE")
        self.assertNotIn(1, insert_params)


if __name__ == "__main__":
    unittest.main()
