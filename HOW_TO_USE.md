# 🤖 JobHunter Bot — How to Use

JobHunter automatically scrapes **Indeed**, **LinkedIn**, and **Glassdoor** every hour and sends you matching jobs via DM!

---

## 🚀 Getting Started

### Step 1: Subscribe
Use the `/subscribe` command to set up a job search.

```
/subscribe keyword: computer science internship location: cluj
```

You'll get a confirmation like:
> ✅ Subscribed! **#1** — `computer science internship` in `cluj` (last 7d)

### Step 2: Wait for Results
The bot scrapes every hour. New jobs matching your search will be sent to your **DMs** automatically.

### Step 3: Manage Your Searches
- `/my_searches` — View all your active subscriptions
- `/unsubscribe id: 1` — Remove a subscription by its ID
- `/scrape_now` — Force an immediate scrape (don't spam this!)

---

## ⭐ Recommended Keywords

### 🎯 `computer science internship` (Best for students!)
This is the **most powerful keyword**. It automatically searches for **20 different job titles** at once:

> software engineer intern, software developer intern, web developer intern, data scientist intern, data analyst intern, data engineer intern, machine learning intern, AI intern, backend developer intern, frontend developer intern, full stack intern, devops intern, cloud engineer intern, cybersecurity intern, IT intern, QA intern, computer science intern, junior developer, graduate software engineer, internship

**One subscription covers everything.** You don't need to subscribe 20 times — just use `computer science internship` and the bot handles the rest.

### Other Smart Keywords

| Keyword | What it searches | Best for |
|---------|-----------------|----------|
| `computer science internship` | 20 intern/junior tech roles | 🎓 CS students looking for internships |
| `computer science` | 18 general tech roles (all levels) | Broad tech job search |
| `cs entry level` | 11 junior/entry/graduate/trainee roles | Recent graduates |
| `tech internship` | 9 tech + product + UX intern roles | Broader tech internships |
| `data science` | 8 data/ML/AI roles | Data-focused careers |
| `software engineering` | 9 dev roles (frontend, backend, etc.) | Software dev jobs |

### Using Your Own Keywords
You can also type any custom keyword — it will be searched as-is on job boards:
```
/subscribe keyword: react developer location: london
```

---

## 📍 Supported Locations

You can type locations casually — the bot understands shortcuts:

| You type | Bot searches |
|----------|-------------|
| `cluj` | Cluj-Napoca, Romania |
| `bucharest` or `bucuresti` | Bucharest, Romania |
| `timisoara` | Timisoara, Romania |
| `iasi` | Iasi, Romania |
| `brasov` | Brasov, Romania |
| `sibiu` | Sibiu, Romania |
| `craiova` | Craiova, Romania |
| `constanta` | Constanta, Romania |
| `oradea` | Oradea, Romania |
| `dublin` | Dublin, Ireland |
| `london` | London, United Kingdom |
| `berlin` | Berlin, Germany |
| `amsterdam` | Amsterdam, Netherlands |
| `romania` | All of Romania |

You can also type any city/country not on this list and it will be searched as-is.

---

## 📅 Max Age

The `max_age_days` option controls how far back to look (default: **7 days**).

```
/subscribe keyword: computer science internship location: dublin max_age_days: 14
```
This searches for jobs posted in the last 2 weeks.

---

## 💡 Tips

1. **Start with `computer science internship`** — it's the best all-in-one keyword for CS students
2. **Add multiple locations** — create one subscription per city you're interested in
3. **Enable DMs** from server members so the bot can message you (Server Settings → Privacy)
4. **Don't duplicate** — one `computer science internship` subscription covers intern + junior + graduate roles automatically
5. **Results are filtered** — the bot removes senior/lead roles and non-tech jobs, so you only see relevant stuff

---

## 📋 Example Setup for a CS Student

```
/subscribe keyword: computer science internship location: cluj max_age_days: 14
/subscribe keyword: computer science internship location: dublin max_age_days: 14
/subscribe keyword: cs entry level location: bucharest max_age_days: 7
```

This gives you full coverage across 3 cities with one command each. 🎉
