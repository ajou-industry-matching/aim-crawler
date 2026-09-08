# 크롤러 인수인계 (softcon crawler)

담당자가 없어도 크롤러를 이해하고 운영할 수 있도록 정리한 문서다. 사이트 구조와 크롤링 메커니즘은 실제 리버스 엔지니어링으로 확인한 내용이다.

## 1. 개요

- 대상: 아주대 소프트콘 전시 사이트 `https://softcon.ajou.ac.kr`.
- 하는 일: 학기별 작품 목록과 상세(제목, 개요, 팀원, GitHub, 대표이미지)를 수집해 JSON/CSV와 이미지로 저장하고, 백엔드로 적재한다.
- 산출물: `output/data/project_links.json`, `output/data/project_details.json`, `output/data/result.csv`, `output/images/`.
- 핵심 파일: `crawler.py` (단일 파일).

## 2. 사이트 구조와 크롤링 메커니즘 (중요)

이 부분을 모르면 데이터를 거의 못 가져온다. 실제로 과거에 학기당 5건만 수집되던 버그가 있었다.

### 2.1 접근 헤더
- 최소 요청은 **HTTP 406**으로 막힌다. 실제 브라우저 User-Agent가 필요하다. `crawler.py`의 `HEADERS`에 Chrome UA가 들어 있고, 이걸로는 200이 온다.

### 2.2 목록은 서버 HTML이 아니라 AJAX로 로드된다
- `works/works_list.asp`, `works/works_list_prev.asp`의 서버 HTML에는 실제 목록이 없다. 그 안의 uid 링크는 **모달(popup) 안의 5건**뿐이다. 이걸 파싱하면 학기당 5건에서 잘린다.
- 실제 전체 목록은 다음 엔드포인트로 페이징해서 받는다.
  - `POST https://softcon.ajou.ac.kr/common/ajax_file/work_list_ajax.asp`
  - form data: `{ "page": <1부터>, "category": <코드>, "wTerm": "<YYYY-N>" }`
  - 헤더: `HEADERS` + `X-Requested-With: XMLHttpRequest`
  - 응답: HTML 조각. 본문이 `"F"`이거나 비어 있거나 `uid=` 링크가 없으면 그 조합의 마지막 페이지다. `page`를 1씩 늘려 끝까지 받는다.
- 목록 아이템의 상세 링크는 `/works/works_prev.asp?uid=339&category=S&wTerm=2020-2` 형태다. 이 절대 URL을 `get_project_details`에 넘긴다.

### 2.3 학기(wTerm)와 카테고리(category)
- 학기: `2020-1`부터 현재까지 존재한다(예: 2020-1 ~ 2026-1). `works_list_prev.asp` 페이지에서 `wTerm=YYYY-N` 값을 정규식으로 뽑아 동적으로 얻는다.
- 카테고리 코드: 사이트는 `S`(소프트웨어), `W`, `I`(인공지능융합), `A` 등을 쓴다. 학기마다 활성 카테고리가 다르다. 예를 들어 `W`는 2020-2에 50건이지만 이후 학기엔 0건이다.
- 주의: `crawler.py`의 `CATEGORY_MAP`은 `S/D/C/I`로 되어 있어 사이트 실제 코드(`S/W/I/A` 등)와 어긋난다. 목록 수집은 `CATEGORY_MAP`에 의존하지 않고 후보 코드를 순회하며 데이터 없는 조합을 건너뛴다. 라벨 매핑이 필요하면 `CATEGORY_MAP`을 실제 코드에 맞게 보정해야 한다.

### 2.4 "현재(current)" 목록은 이벤트 사이엔 비어 있다
- `works_list.asp?category=S`(현재 전시)는 등록된 작품이 없으면 "등록된 작품이 없습니다"를 보여준다. 소프트콘은 주기적 경진대회라 이벤트 사이엔 현재 목록이 비어 0건이 정상이다. 과거 학기(prev)에는 데이터가 계속 있다.

### 2.5 상세 파서 주의점
- `get_project_details`가 대표이미지로 등록자 기본 이미지(`no_registrant.jpg`)를 가져오는 경우가 있다. 작품 실제 썸네일이 아닐 수 있으니 이미지 품질이 중요하면 상세 파서의 이미지 선택 로직을 점검한다.
- 목록 링크의 `title`은 버튼 텍스트("상세보기")로 잡히지만, 실제 제목은 상세 페이지에서 다시 가져오므로 최종 데이터는 정상이다.

## 3. 실행 방법

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # requests, beautifulsoup4, lxml, pymysql
python crawler.py
```

- `main()` 흐름: 전체 목록 수집(`get_all_project_links`) → 상세 수집 + 이미지 다운로드 → JSON/CSV 저장 → 적재(아래 4절).
- 요청 간 `DELAY`(기본 1초)로 사이트를 과도하게 두드리지 않는다.
- `MAX_PROJECTS`는 상세 수집 개수 상한이다. 기본 `None`(무제한). 테스트 시 env `MAX_PROJECTS=20`처럼 제한할 수 있다.

## 4. 데이터 적재 (두 가지 모드)

`main()`은 아래 순서로 적재 방식을 고른다.

1. `BACKEND_API_BASE_URL` + `CRAWLER_API_TOKEN`이 둘 다 있으면 **API 전송**(`post_to_api`).
2. 없으면 **DB 직접 적재**(`save_to_db`, 레거시).

### API 전송 (권장)
- `POST {BACKEND_API_BASE_URL}/api/crawled-projects`, 헤더 `Authorization: Bearer {CRAWLER_API_TOKEN}`.
- 백엔드 스키마(`CrawledProjectCreateRequest`)로 매핑한다: `uid, term, title, summary, description, content, url, presentationUrl, videoUrl, gitRepository, representativeImage, category, members[]`.
- 개인정보 보호: 참여자 이메일은 `members[].maskedEmail`로만 보낸다. `content`에는 원본 이메일이 담긴 팀 정보를 넣지 않는다.
- 보안: `BACKEND_API_BASE_URL`이 `https://`가 아니면 전송을 중단한다(토큰 평문 전송 방지).
- 멱등: 백엔드가 `(uid, term)` 기준 upsert라 재전송해도 안전하다.

### DB 직접 적재 (레거시)
- 운영 DB는 Oracle Cloud MySQL `161.33.46.41:3306/aim`, 테이블 소문자 `posts`/`users`.
- `posts.user_id` FK 때문에 크롤러 전용 시스템 유저를 자동 생성하는 옵션이 있다.
- 시크릿(DB 비밀번호 등)은 GitHub Actions Secret/Variable과 GCP Secret Manager로 주입한다.

## 5. 백엔드 API 의존성

- `POST /api/crawled-projects`는 `ADMIN`/`SUPER_ADMIN` 전용이다. 백엔드 인증은 Firebase ID 토큰 검증 방식이다.
- 헤드리스 크롤러가 쓸 **관리자 토큰(`CRAWLER_API_TOKEN`) 발급 방식은 아직 미확정**이다. 결정 전까지 API 전송은 운영에 투입할 수 없다. (aim-backend#49)

## 6. 환경변수 (.env)

- 크롤 대상: `LIST_TYPE`, `CATEGORY`, `TERM`, `MAX_PROJECTS`.
- API 전송: `BACKEND_API_BASE_URL`, `CRAWLER_API_TOKEN`.
- DB 적재: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, 크롤러 시스템 유저 관련(`CRAWLER_USER_*`, `DB_AUTO_CREATE_CRAWLER_USER`), 테이블명(`DB_POST_TABLE`, `DB_USER_TABLE`).
- `.env.example` 참고.

## 7. 관련 PR / 이슈

- aim-crawler#9: 크롤 결과를 백엔드 크롤링 API로 전송(API 싱크) + 보안 수정(https 강제, content 원본 이메일 제거).
- aim-crawler#10: 전체 목록 수집(AJAX 페이징, 전 학기·전 카테고리). #9 위에 스택.
- aim-backend#49: 크롤러용 관리자 인증 토큰 발급 방식 결정.
