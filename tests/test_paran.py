import os
import unittest

import crawler

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "paran_2024-1_sample.html"
)


class ParanParseTest(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE, encoding="utf-8") as f:
            self.html = f.read()
        self.items = crawler.parse_paran_rows(
            "2024-1", "https://www.ajou.ac.kr/ace/paran/2024-1.do", self.html
        )

    def test_parses_rows_and_skips_blank_title(self):
        # 샘플: 실제 3행 + 제목이 빈 1행 → 빈 제목 행은 건너뛴다.
        self.assertEqual(len(self.items), 3)
        self.assertNotIn("", [i["title"] for i in self.items])

    def test_maps_to_backend_schema(self):
        first = self.items[0]
        self.assertEqual(first["uid"], "paran-ACP")           # paran- 네임스페이스
        self.assertEqual(first["term"], "2024-1")             # softcon과 동일 포맷
        self.assertEqual(first["title"], "소상공인 컨설팅")   # 도전과제명 = title
        self.assertEqual(first["category"], "파란학기제")
        self.assertIn("팀명: ACP", first["content"])          # 팀명 보존
        self.assertIn("인원수: 팀(6명)", first["content"])
        self.assertEqual(first["teamInfo"], {})               # 멤버 정보 없음

    def test_source_uid_namespaced_and_bounded(self):
        # 소프트콘 숫자 uid와 겹치지 않고 길이 100 이하 보장.
        long_uid = crawler.paran_source_uid("1", "가" * 200)
        self.assertTrue(long_uid.startswith("paran-"))
        self.assertLessEqual(len(long_uid), 100)


if __name__ == "__main__":
    unittest.main()
