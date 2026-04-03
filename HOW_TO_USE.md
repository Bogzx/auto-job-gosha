# GOSHA — How to Use

GOSHA automatically scrapes **Indeed**, **LinkedIn**, and **Glassdoor** every hour and sends you matching jobs via DM!

---

## Quick Start (Fastest Way)

```
/quickstart location: cluj
```

That's it! This creates a subscription for **20 CS internship/junior job titles** in your chosen city. You'll start receiving matching jobs via DM.

---

## Custom Subscriptions

### `/subscribe` — Create a Search

```
/subscribe keyword: computer science internship location: cluj
```

You'll get a confirmation showing exactly what will be searched.

**Options you can add:**

| Option | Description | Example |
|--------|-------------|---------|
| `experience` | Filter by level (dropdown) | `Intern / Internship` |
| `max_age_days` | How far back to look (default 7) | `14` |
| `exclude` | Remove jobs containing these words | `sales, marketing` |
| `salary_min` | Minimum annual salary | `30000` |

### Smart Keywords

When you pick a smart keyword, the bot searches **many specific job titles** at once:

| Keyword | Titles Searched | Best For |
|---------|----------------|----------|
| `computer science internship` | 20 intern/junior tech roles | CS students looking for internships |
| `computer science` | 18 general tech roles (all levels) | Broad tech job search |
| `cs entry level` | 11 junior/graduate/trainee roles | Recent graduates |
| `tech internship` | 9 tech + product + UX intern roles | Broader tech internships |
| `data science` | 8 data/ML/AI roles | Data-focused careers |
| `software engineering` | 9 dev roles (frontend, backend, etc.) | Software dev jobs |

Use `/show_keywords computer science internship` to see the full list of titles.

You can also type **any custom keyword** — it will be searched as-is on job boards.

---

## Supported Locations

Start typing in the location field and you'll see suggestions. Supported shortcuts:

### Romania
`cluj` · `bucharest` / `bucuresti` · `timisoara` · `iasi` · `brasov` · `sibiu` · `craiova` · `constanta` · `oradea` · `romania` (all cities)

### Europe
`dublin` · `london` · `berlin` · `amsterdam` · `prague` · `warsaw` · `budapest` · `krakow` · `vienna` · `munich` · `paris` · `barcelona` · `zurich`

### Remote
`remote` — matches jobs listed as remote, work-from-home, or anywhere.

You can also type any city/country not on this list.

---

## Managing Subscriptions

| Command | What it does |
|---------|-------------|
| `/my_searches` | View all your subscriptions |
| `/edit id:1 keyword:new terms` | Modify a subscription |
| `/unsubscribe id:1` | Delete a subscription |
| `/pause id:1` | Temporarily stop receiving jobs |
| `/resume id:1` | Resume a paused subscription |

---

## Other Commands

| Command | What it does |
|---------|-------------|
| `/scrape_now` | Force an immediate scrape (cooldown applies) |
| `/stats` | See your delivery statistics |
| `/status` | Check bot health and uptime |
| `/show_keywords keyword` | See what job titles a smart keyword expands to |
| `/help` | Show all commands in Discord |

---

## Tips

1. **Start with `/quickstart`** — it's the fastest way to get going
2. **Use smart keywords** — one `computer science internship` subscription covers 20 job titles
3. **Enable DMs** from server members so the bot can message you (Server Settings > Privacy)
4. **Use the buttons** — click "Interested" or "Not Relevant" on job DMs to train the bot
5. **Click "Apply"** — each job DM has an Apply button that takes you straight to the posting
6. **Add exclusions** — if you keep getting irrelevant jobs, use `/edit` to add excluded keywords

---

## Example Setup for a CS Student in Romania

```
/quickstart location: romania
```

Or for more control:

```
/subscribe keyword: computer science internship location: cluj, bucharest experience: Intern / Internship max_age_days: 14
/subscribe keyword: data science location: remote experience: Junior / Entry Level
```

---

## Free vs Pro

| Feature | Free | Pro |
|---------|------|-----|
| Subscriptions | 2 | 10 |
| Keywords per subscription | 3 | 10 |
| Locations per subscription | 2 | 10 |
| Scrape-now cooldown | 10 min | 2 min |
| Semantic matching | No | Yes |
| Email delivery | No | Yes |
