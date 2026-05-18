# Cloud Run Job DB 설정

이 크롤러는 AIM 백엔드의 `POSTS` 테이블에 `CRAWLED_PROJECT` 게시글로 저장한다.
백엔드 엔티티 기준 컬럼 매핑은 다음과 같다.

| 크롤러 필드 | DB 컬럼 |
| --- | --- |
| 관리자/시스템 유저 ID | `user_id` |
| 고정값 `CRAWLED_PROJECT` | `board_type` |
| `title` | `title` |
| `description` 또는 `summary` | `description` |
| `summary`, `presentationUrl`, `url`, `term`, `uid`, `teamInfo` | `content` |
| `representativeImage` | `thumbnail_image` |
| `softcon:{term}:{uid}` | `thumbnail_storage_key` |
| `videoUrl` | `video_link` |
| `gitRepository` | `github_link` |
| 고정값 `PUBLIC` | `visibility` |

`thumbnail_storage_key`는 소프트콘 원본 항목을 식별하는 키로 사용한다.
같은 키가 이미 있으면 새 행을 만들지 않고 기존 `POSTS` 행을 업데이트한다.

## 필수 환경변수

| 이름 | 설명 |
| --- | --- |
| `DB_USER` | MySQL 사용자 |
| `DB_PASSWORD` | MySQL 비밀번호. Cloud Run에서는 Secret Manager 사용 |
| `DB_NAME` | MySQL 데이터베이스명 |
| `CRAWLER_USER_ID` | `USERS.user_id`에 존재하는 관리자 또는 시스템 유저 ID |
| `DB_POST_TABLE` | 기본값 `POSTS`. 실제 스키마가 소문자면 `posts`로 설정 |

TCP 접속을 쓰면 `DB_HOST`, `DB_PORT`를 설정한다.
Cloud SQL Unix socket 접속을 쓰면 `CLOUD_SQL_CONNECTION_NAME` 또는 `DB_UNIX_SOCKET`을 설정한다.

## Oracle Cloud MySQL 예시

```bash
printf %s "$DB_PASSWORD" \
  | gcloud secrets create DB_PASSWORD --data-file=- --replication-policy=automatic

gcloud run jobs update softcon-crawler \
  --region asia-northeast3 \
  --update-env-vars "LIST_TYPE=current,CATEGORY=S,MAX_PROJECTS=50,DB_HOST=<MYSQL_HOST>,DB_PORT=3306,DB_USER=<MYSQL_USER>,DB_NAME=<MYSQL_DB>,CRAWLER_USER_ID=<ADMIN_USER_ID>,DB_POST_TABLE=POSTS" \
  --update-secrets "DB_PASSWORD=DB_PASSWORD:latest"
```

Oracle Cloud Security List 또는 NSG에는 Cloud Run에서 나가는 IP가 MySQL `3306` 인바운드 허용 목록에 포함되어야 한다.

## Cloud SQL 예시

```bash
printf %s "$DB_PASSWORD" \
  | gcloud secrets create DB_PASSWORD --data-file=- --replication-policy=automatic

gcloud run jobs update softcon-crawler \
  --region asia-northeast3 \
  --add-cloudsql-instances "ajou-project-cafd9:asia-northeast3:aim-be-db" \
  --update-env-vars "LIST_TYPE=current,CATEGORY=S,MAX_PROJECTS=50,CLOUD_SQL_CONNECTION_NAME=ajou-project-cafd9:asia-northeast3:aim-be-db,DB_USER=<MYSQL_USER>,DB_NAME=<MYSQL_DB>,CRAWLER_USER_ID=<ADMIN_USER_ID>,DB_POST_TABLE=POSTS" \
  --update-secrets "DB_PASSWORD=DB_PASSWORD:latest"
```

이미 `DB_PASSWORD` 시크릿이 있으면 `gcloud secrets versions add DB_PASSWORD --data-file=-`로 새 버전을 추가한다.

## 실행 확인

```bash
gcloud run jobs execute softcon-crawler \
  --region asia-northeast3 \
  --wait

gcloud run jobs executions list \
  --job softcon-crawler \
  --region asia-northeast3
```

로그에 `[OK] DB 저장 완료 (insert N건, update M건)`이 보여야 한다.
DB 설정이 전혀 없으면 로컬 파일 저장만 수행하고 `[DB] DB 환경변수가 없어 저장을 건너뜁니다.`를 출력한다.
