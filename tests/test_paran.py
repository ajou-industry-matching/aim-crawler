import os
import unittest

import crawler

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures")
LIST_FIXTURE = os.path.join(FIXDIR, "paran_conference_list.html")      # conference.do 목록(실제 HTML 축약)
DETAIL_FIXTURE = os.path.join(FIXDIR, "paran_conference_detail.html")  # conference.do 상세(실제 HTML 축약)


class ParanListParseTest(unittest.TestCase):
    def setUp(self):
        with open(LIST_FIXTURE, encoding="utf-8") as f:
            self.rows = crawler.parse_paran_list(f.read())

    def test_parses_rows(self):
        self.assertEqual(len(self.rows), 3)

    def test_articleno_term_title_image(self):
        first = self.rows[0]
        self.assertEqual(first["articleNo"], "376575")
        self.assertEqual(first["term"], "2026-2")                 # 제목 접두 [2026년도 - 2학기] → 2026-2
        self.assertIn("수원시 건강가정지원센터", first["title"])  # 도전과제명(b-text-box)
        self.assertTrue(first["url"].endswith("articleNo=376575"))
        self.assertTrue(first["representativeImage"].startswith("https://www.ajou.ac.kr/"))

    def test_term_varies_per_row(self):
        # 같은 목록 페이지에 학기가 섞여 있어도 각 행에서 개별 도출된다.
        self.assertEqual(self.rows[1]["term"], "2026-1")

    def test_empty_page_stops_paging(self):
        # 빈/글 없는 페이지 → 빈 리스트(호출부의 offset 루프 종료 조건).
        self.assertEqual(crawler.parse_paran_list(""), [])


class ParanDetailParseTest(unittest.TestCase):
    def setUp(self):
        with open(DETAIL_FIXTURE, encoding="utf-8") as f:
            self.d = crawler.parse_paran_detail(
                f.read(),
                "https://www.ajou.ac.kr/ace/paran/conference.do?mode=view&articleNo=376563",
            )

    def test_title_and_team_name(self):
        self.assertIn("수원시 교통약자지원센터", self.d["title"])      # 도전과제명 = title
        self.assertEqual(self.d["teamInfo"]["teamName"], "수원이가 좋아할 지도")

    def test_members_leader_members_professor(self):
        # 숨은 input(JSON)에서 팀장/팀원/지도교수를 복원한다.
        members = self.d["teamInfo"]["members"]
        roles = [m["role"] for m in members]
        self.assertEqual(roles.count("팀장"), 1)
        self.assertEqual(roles.count("팀원"), 2)
        self.assertEqual(roles.count("지도교수"), 1)

        leader = members[0]
        self.assertEqual(leader["role"], "팀장")
        self.assertEqual(leader["name"], "이소흔")
        self.assertEqual(leader["department"], "산업공학과")
        self.assertEqual(leader["grade"], "2")
        # 이메일은 사이트가 화면에서만 JS로 마스킹한다 → 원문 로컬파트가 input에 들어있어 복원 가능.
        self.assertEqual(leader["email"], "soheun1004@ajou.ac.kr")

        # 팀원 이메일: teamMemberEmail[i] 로컬 + [i+9] 도메인.
        member_emails = [m["email"] for m in members if m["role"] == "팀원"]
        self.assertEqual(member_emails, ["kahyxn@ajou.ac.kr", "hahshshw@ajou.ac.kr"])

        # 지도교수는 이메일이 없다.
        prof = [m for m in members if m["role"] == "지도교수"][0]
        self.assertEqual(prof["name"], "정슬기")
        self.assertEqual(prof["email"], "")

    def test_summary_and_video(self):
        self.assertIn("수원이가 좋아할 지도", self.d["summary"])        # 작품개요(fr-view)
        self.assertIn("youtube.com", self.d["videoUrl"])


class ParanSourceUidTest(unittest.TestCase):
    def test_articleno_namespaced(self):
        # articleNo 기반 안정적 uid, 소프트콘 숫자 uid와 "paran-"로 구분.
        self.assertEqual(crawler.paran_source_uid("376563"), "paran-376563")
        self.assertEqual(crawler.paran_source_uid(199319), "paran-199319")


if __name__ == "__main__":
    unittest.main()
