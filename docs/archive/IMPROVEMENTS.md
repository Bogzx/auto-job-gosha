# JobHunter Bot - Improvement Brainstorm

## 1. Reliability & Resilience

### 1.1 Auto-restart dead SSH tunnels
Right now if an SSH tunnel process exits, it stays dead until the entire bot restarts. A background watchdog (checked every ~30s) could detect dead tunnels and respawn them automatically, keeping proxy rotation healthy.

### 1.2 Rate-limit `/scrape_now`
Any user can spam `/scrape_now` and hammer the job boards. Add a cooldown (e.g., once per 15 minutes globally or per user) to prevent abuse and potential IP bans.

### 1.3 Retry logic for failed scrapes
If a scrape fails (network timeout, proxy down, job board blocking), there's no retry. A simple retry with exponential backoff (2-3 attempts) per expanded keyword would improve hit rate without much complexity.

### 1.4 Seen jobs table cleanup
`seen_jobs` grows forever. A periodic cleanup (e.g., delete entries older than 60 days) would keep the database lean. Old seen_jobs records are useless since those job postings are long expired anyway.

### 1.5 Health check / status command
A `/status` command showing: last scrape time, number of active proxies, number of active subscriptions, database size, and uptime. Useful for diagnosing issues without SSH-ing into the server.

---

## 2. Smarter Scraping & Filtering

### 2.1 Cross-board deduplication
The same job often appears on Indeed, LinkedIn, and Glassdoor. Currently dedup is URL-based, so the same position from different boards gets sent 2-3 times. Fuzzy matching on (company + title + location) could merge these into a single notification with multiple apply links.

### 2.2 AI-powered job description summarization
Job descriptions are truncated at 200 chars in the DM embed. Using a lightweight LLM call (or even a simple extractive summarizer) to pull out key requirements, salary info, and tech stack would make the DM much more useful without the user needing to click through.

### 2.3 Salary filtering
Let users set a minimum salary in their subscription. JobSpy sometimes returns salary data — filter out jobs below the threshold, or at least surface salary info prominently in the embed when available.

### 2.4 Better location matching
The current substring-based location matching has edge cases (e.g., "London, Ontario" vs "London, UK"). Using a geocoding API or a structured location hierarchy would be more accurate.

### 2.5 More job boards
Expand beyond Indeed/LinkedIn/Glassdoor. Good candidates:
- **eJobs.ro** and **BestJobs.ro** — critical for Romanian market (which seems to be the primary use case)
- **RemoteOK / WeWorkRemotely** — for remote-first roles
- **Hipo.ro** — another Romanian job board
- **AngelList/Wellfound** — for startup jobs

### 2.6 Remote job support
Add a `remote: true` flag to subscriptions. When enabled, also search remote-specific boards and include "remote" in the location filter. Many CS internships and entry-level roles are remote now.

---

## 3. User Experience

### 3.1 Interactive buttons on job embeds
Discord supports message components (buttons). Add:
- **"Save"** button — bookmarks the job for later
- **"Not interested"** button — trains the filter (see 3.2)
- **"Apply"** button — direct link to application page

### 3.2 Feedback loop for relevance
Let users thumbs-up/thumbs-down jobs. Track which job titles/companies users like/dislike. Over time, prioritize or filter based on this feedback. Even simple rules ("user always dismisses company X" -> stop showing company X) would help.

### 3.3 Company blacklist
`/block_company Google` — never show jobs from that company. Useful when users have already applied somewhere or know they don't want to work there.

### 3.4 Keyword blacklist / exclude terms
`/subscribe keyword: software intern location: cluj exclude: unpaid, volunteer` — filter out jobs whose title or description contains excluded terms.

### 3.5 Pause/resume subscriptions
`/pause 1` and `/resume 1` — temporarily disable a subscription without deleting it. Useful during exam periods or when the user has accepted an offer but wants to keep the subscription for later.

### 3.6 Digest mode
Instead of getting DMs for every single job as they're found, offer a daily or weekly digest — one message with all new jobs grouped by subscription. Less noisy, better for users who prefer batch processing.

### 3.7 Job count estimate on subscribe
When a user creates a subscription, do a quick scrape and report: "Found ~45 matching jobs in the last 7 days. Expect roughly 6-7 new jobs per day." Sets expectations and confirms the subscription is working.

---

## 4. Application Tracking

### 4.1 Basic application tracker
Add a `/applied <job_url>` command that marks a job as "applied to." Then:
- Stop showing that job in future results
- `/my_applications` lists all jobs the user has applied to with dates
- Optional status tracking: applied -> interview -> offer -> rejected

This turns the bot from a job finder into a lightweight job hunt companion.

### 4.2 Application reminders
If a user saves a job but doesn't mark it as applied within X days, send a gentle reminder: "You saved 3 jobs last week but haven't applied yet. Here they are again."

---

## 5. Infrastructure & Operations

### 5.1 Database migration support
Add Alembic for schema migrations. Right now any schema change requires manual DB manipulation or a fresh start. As features are added, migrations become essential.

### 5.2 PostgreSQL option
SQLite works for small scale, but if more users join, connection concurrency becomes a problem with async SQLite. Make the database backend configurable (SQLite for dev, PostgreSQL for prod). The SQLAlchemy async layer already supports this — it's mostly a connection string change.

### 5.3 Logging improvements
- Structured JSON logging (easier to parse in production)
- Log rotation / size limits
- Per-scrape summary log line with stats (jobs found, filtered, sent, errors)

### 5.4 Monitoring & metrics
Expose basic metrics (Prometheus-style or just a JSON endpoint):
- Scrapes per hour, success/failure rate
- Jobs found/sent per scrape cycle
- Active users, active subscriptions
- Proxy health (tunnel uptime)

### 5.5 Automated tests
No tests exist currently. Priority test areas:
- Keyword expansion logic
- Location alias resolution
- Title relevance filtering (the regex-heavy logic is most likely to break)
- Database operations (subscribe, unsubscribe, dedup)
- Mock-based scraper tests

### 5.6 CI/CD pipeline
GitHub Actions workflow: lint, test, build Docker image, push to registry. Makes deployment more reliable and catches regressions.

---

## 6. Multi-User & Social Features

### 6.1 Subscription limits
Cap subscriptions per user (e.g., 10) to prevent one user from overloading the scraper with dozens of searches.

### 6.2 Admin commands
`/admin_stats` — show total users, subscriptions, jobs sent, database size. Restrict to bot owner/admin role.
`/admin_broadcast` — send a message to all users (for maintenance announcements).

### 6.3 Shared job board channel
Optionally post all found jobs to a shared Discord channel (not just DMs). Users can browse, react, and discuss. This creates a community around job hunting.

### 6.4 Referral / tip sharing
If a user finds a job useful, let them `/share <job_id>` to post it to a shared channel with their recommendation note.

---

## 7. Quick Wins (Low Effort, High Impact)

| Improvement | Effort | Impact |
|---|---|---|
| Rate-limit `/scrape_now` | ~30 min | Prevents abuse |
| `/status` command | ~1 hour | Quality of life |
| Seen jobs cleanup cron | ~30 min | Database health |
| SSH tunnel auto-restart | ~1-2 hours | Reliability |
| Pause/resume subscriptions | ~1 hour | User convenience |
| Company blacklist | ~1-2 hours | Relevance |
| Subscription limits | ~30 min | Safety |
| Add salary to embed when available | ~30 min | Better info |

---

## Priority Recommendation

**Phase 1 — Stability (do first):**
- 1.1 SSH tunnel auto-restart
- 1.2 Rate-limit `/scrape_now`
- 1.4 Seen jobs cleanup
- 5.5 Automated tests (at least for filtering logic)

**Phase 2 — Better results:**
- 2.1 Cross-board deduplication
- 2.5 Romanian job boards (eJobs, BestJobs)
- 3.3 Company blacklist
- 3.5 Pause/resume

**Phase 3 — Power features:**
- 3.1 Interactive buttons
- 3.6 Digest mode
- 4.1 Application tracker
- 2.2 AI summarization

**Phase 4 — Scale & ops:**
- 5.1 Alembic migrations
- 5.5-5.6 Tests & CI/CD
- 5.4 Monitoring
