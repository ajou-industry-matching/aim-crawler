# Cloud Run Job DB 설정

이 크롤러는 Oracle Cloud MySQL의 AIM 백엔드 DB에 접속해 `posts` 테이블에 `CRAWLED_PROJECT` 게시글로 저장한다.

## 현재 운영 DB 값

| 이름 | 값 |
| --- | --- |
| `DB_HOST` | `161.33.46.41` |
| `DB_PORT` | `3306` |
| `DB_USER` | `aim_be` |
| `DB_NAME` | `aim` |
| `DB_POST_TABLE` | `posts` |
| `DB_USER_TABLE` | `users` |
| `CRAWLER_USER_ID` | 현재 운영 DB의 `users`가 비어 있어 기본값 없음 |

`DB_PASSWORD`는 저장소 파일에 넣지 않고 Secret Manager 또는 GitHub Secret으로만 관리한다.

현재 확인된 운영 DB 상태:

- `posts` 테이블은 존재하고 크롤러 SQL에서 쓰는 컬럼과 맞는다.
- `users` 테이블은 존재하지만 비어 있다.
- `posts.user_id`는 `users.user_id` FK라서 기준 유저 없이 insert하면 실패한다.
- 그래서 `CRAWLER_USER_ID`를 직접 지정하거나 `DB_AUTO_CREATE_CRAWLER_USER=true`로 크롤러 전용 유저를 생성해야 한다.

## 필수 환경변수

| 이름 | 설명 |
| --- | --- |
| `DB_HOST` | Oracle Cloud MySQL 호스트 |
| `DB_PORT` | MySQL 포트 |
| `DB_USER` | MySQL 사용자 |
| `DB_PASSWORD` | MySQL 비밀번호. Cloud Run에서는 Secret Manager 사용 |
| `DB_NAME` | MySQL 데이터베이스명 |
| `CRAWLER_USER_ID` | `users.user_id`에 존재하는 관리자 또는 시스템 유저 ID. 없으면 비워둘 수 있음 |
| `DB_AUTO_CREATE_CRAWLER_USER` | `CRAWLER_USER_ID`가 없을 때 전용 시스템 유저를 생성하려면 `true` |
| `CRAWLER_USER_EMAIL` | 자동 생성 유저 이메일. 기본 `softcon-crawler@aim.local` |
| `CRAWLER_USER_FIREBASE_UID` | 자동 생성 유저 firebase UID. 기본 `softcon-crawler` |
| `CRAWLER_USER_NAME` | 자동 생성 유저 이름. 기본 `Softcon Crawler` |
| `DB_POST_TABLE` | 운영 DB 기준 `posts` |
| `DB_USER_TABLE` | 운영 DB 기준 `users` |

## Secret Manager 등록

이미 `DB_PASSWORD` 시크릿이 없으면 생성한다.

```bash
read -r -s DB_PASSWORD
printf %s "$DB_PASSWORD" \
  | gcloud secrets create DB_PASSWORD \
      --project ajou-project-cafd9 \
      --data-file=- \
      --replication-policy=automatic
```

이미 시크릿이 있으면 새 버전을 추가한다.

```bash
read -r -s DB_PASSWORD
printf %s "$DB_PASSWORD" \
  | gcloud secrets versions add DB_PASSWORD \
      --project ajou-project-cafd9 \
      --data-file=-
```

Cloud Run Job 서비스 계정에는 Secret Manager 접근 권한이 필요하다.

```bash
gcloud secrets add-iam-policy-binding DB_PASSWORD \
  --project ajou-project-cafd9 \
  --member "serviceAccount:<CLOUD_RUN_JOB_SERVICE_ACCOUNT>" \
  --role roles/secretmanager.secretAccessor
```

## Cloud Run Job 환경변수

```bash
gcloud run jobs update softcon-crawler \
  --project ajou-project-cafd9 \
  --region asia-northeast3 \
  --update-env-vars "LIST_TYPE=current,CATEGORY=S,MAX_PROJECTS=50,TERM=2024-1,DB_HOST=161.33.46.41,DB_PORT=3306,DB_USER=aim_be,DB_NAME=aim,DB_AUTO_CREATE_CRAWLER_USER=true,CRAWLER_USER_EMAIL=softcon-crawler@aim.local,CRAWLER_USER_FIREBASE_UID=softcon-crawler,CRAWLER_USER_NAME=Softcon Crawler,DB_POST_TABLE=posts,DB_USER_TABLE=users" \
  --update-secrets "DB_PASSWORD=DB_PASSWORD:latest"
```

기존 관리자/시스템 유저가 생기면 `CRAWLER_USER_ID=<실제 user_id>`를 넣고 `DB_AUTO_CREATE_CRAWLER_USER=false`로 바꿔도 된다.

## Oracle Cloud 방화벽

Oracle Cloud Security List 또는 NSG에는 Cloud Run에서 나가는 IP가 MySQL `3306` 인바운드 허용 목록에 포함되어야 한다. Cloud Run 기본 egress는 고정 IP가 아니므로, 운영에서 IP allowlist가 필요하면 Serverless VPC Access와 Cloud NAT 고정 IP 구성을 같이 확인한다.

## 실행 확인

```bash
gcloud run jobs execute softcon-crawler \
  --project ajou-project-cafd9 \
  --region asia-northeast3 \
  --wait
```

정상 실행 시 로그에 `[OK] DB 저장 완료 (insert N건, update M건)` 형식의 메시지가 출력된다.
