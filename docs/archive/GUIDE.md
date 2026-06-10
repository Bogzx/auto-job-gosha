# **JobHunter Bot** — Your AI-Powered Job Search Assistant

Stop scrolling through job boards. **JobHunter** automatically finds CS internships and junior roles from **LinkedIn, Indeed, and Glassdoor**, matches them to your preferences, and sends them straight to your DMs — with **AI-generated cover letters** tailored to each job.

---

## **Getting Started (30 seconds)**

### Step 1 — Quick Setup
Type this in any channel where the bot is present:
```
/quickstart location: Cluj
```
> Replace `Cluj` with your city. This creates a starter subscription for **CS internships** and **junior roles** — it searches **19 job titles** automatically.

### Step 2 — Upload Your CV
```
/upload_cv
```
> Attach your CV as a **PDF**, **DOCX**, or **TXT** file (max 5 MB). This enables AI cover letter generation for every job you receive.

### Step 3 — Get Jobs Now
```
/scrape_now
```
> Forces an immediate search. Otherwise, jobs are checked automatically **every 4 hours** and sent to your **DMs**.

**That's it. You're set up.**

---

## **How Jobs Are Delivered**

Jobs arrive in your **Discord DMs** as rich embeds with:

- **Job title, company, location, salary** (when available)
- **Relevance score** (0-100%) — how well the job matches your search
- **Description preview** — first 300 characters
- **Source** — LinkedIn, Indeed, or Glassdoor

### Interactive Buttons on Every Job

| Button | What it does |
|--------|-------------|
| **Apply** | Opens the job posting URL directly |
| **Cover Letter** | Generates an AI cover letter using your CV + this job's details |
| **Interested** | Tells the bot you like this type of job (improves future matches) |
| **Not Relevant** | Tells the bot to show fewer jobs like this |

> **Tip:** The more feedback you give, the better your matches get over time.

---

## **Commands Reference**

### Subscriptions

| Command | What it does |
|---------|-------------|
| `/subscribe keyword: ... location: ...` | Create a new job search |
| `/my_searches` | View all your active subscriptions |
| `/edit id: ...` | Modify a subscription's keywords, location, etc. |
| `/pause id: ...` | Temporarily stop a subscription |
| `/resume id: ...` | Resume a paused subscription |
| `/unsubscribe id: ...` | Delete a subscription |

### Job Discovery

| Command | What it does |
|---------|-------------|
| `/scrape_now` | Force an immediate job search |
| `/stats` | See how many jobs you've received and your feedback stats |
| `/show_keywords keyword: ...` | Preview which job titles a keyword expands into |

### Applications Tracker

| Command | What it does |
|---------|-------------|
| `/apply job_id: ...` | Track that you applied to a job |
| `/update_application job_id: ... status: ...` | Update status (Phone Screen, Interview, Offer, etc.) |
| `/applications` | View all your tracked applications by status |

### AI Cover Letters

| Command | What it does |
|---------|-------------|
| `/upload_cv` | Upload your CV (PDF/DOCX/TXT) |
| `/cover_letter job_id: ...` | Generate a cover letter for a specific job |
| `/my_cv` | Preview your stored CV and check monthly usage |
| `/delete_cv` | Remove your stored CV |

### Other

| Command | What it does |
|---------|-------------|
| `/quickstart` | One-click setup for CS students |
| `/upgrade` | View plan details and limits |
| `/help` | Show all commands |

---

## **Smart Keywords**

When you subscribe, certain keywords **auto-expand** into many related job titles:

| Keyword | Expands to |
|---------|-----------|
| `computer science internship` | 19 titles — software engineer intern, data analyst intern, QA intern, frontend/backend intern, etc. |
| `computer science` | 18 titles — software engineer, full stack developer, data scientist, DevOps engineer, etc. |
| `cs entry level` | 11 titles — junior developer, graduate software engineer, trainee, etc. |
| `software engineering` | 9 titles — software developer, full stack, backend, frontend, etc. |
| `data science` | 8 titles — data scientist, ML engineer, data analyst, BI analyst, etc. |
| `tech internship` | 9 titles — software intern, product intern, UX intern, etc. |

> Use `/show_keywords keyword: computer science internship` to see the full expansion list.

---

## **Supported Locations**

**Romanian cities:** Cluj, Bucharest, Timisoara, Iasi, Brasov, Sibiu, Oradea, Craiova, Constanta

**European tech hubs:** Berlin, Munich, Amsterdam, London, Dublin, Paris, Barcelona, Zurich, Prague, Warsaw, Budapest, Vienna, Krakow

**Broad searches:** `Romania`, `Europe`, `EU`, `Remote`

> `Remote` matches remote, work-from-home, and hybrid roles. All subscriptions also include remote jobs by default.

---

## **AI Cover Letters**

1. Upload your CV once with `/upload_cv`
2. When you see a job you like, click the **Cover Letter** button or use `/cover_letter job_id: 42`
3. The AI reads your CV + the job posting and writes a **tailored cover letter** (250-350 words)
4. Cover letters are cached — requesting the same one again won't use your monthly quota

**Free plan:** 5 cover letters/month

---

## **Pro Tips**

- **Use multiple subscriptions** — create one for `computer science internship` in `Cluj` and another for `software engineering` in `Remote`
- **Exclude irrelevant terms** — `/subscribe keyword: software engineer location: Romania exclude: sales, marketing, senior`
- **Blacklist companies** — `/edit id: 1 blacklist: Accenture, Cognizant`
- **Give feedback on every job** — click Interested or Not Relevant to train your personal matching profile. After 3+ ratings, the bot learns your preferences
- **Track your applications** — use `/apply` and `/update_application` to keep a pipeline of where you've applied

---

## **FAQ**

**Q: I'm not receiving any DMs?**
> Make sure your Discord DMs are enabled for this server. Go to **Server Settings > Privacy Settings > Allow direct messages from server members**.

**Q: How often are jobs checked?**
> Every 4 hours automatically. Use `/scrape_now` to trigger an immediate check.

**Q: Where do jobs come from?**
> LinkedIn, Indeed, and Glassdoor — scraped in real-time with deduplication across all three.

**Q: Can I search for non-CS jobs?**
> Yes! Use any custom keyword — `marketing intern`, `graphic designer`, `mechanical engineer`, etc. Smart expansion only applies to the predefined CS keywords.

**Q: How is the relevance score calculated?**
> AI semantic matching compares your subscription (keywords + location + experience level) against the job posting using a neural language model. Your feedback history further adjusts the score.

---

*Built for CS students, by a CS student. Good luck with your job search!*
