# IMT Pulse, by Raj Srivastava

**An AI-generated daily business brief and quiz app for MBA students preparing for campus placements.**
Built for IMT Ghaziabad in October 2026 and piloted with real students.

Every morning at 05:30 IST a serverless pipeline reads ~450 headlines from Indian business news RSS feeds and
uses LLMs on Amazon Bedrock to produce, for each of 5 career tracks (Marketing, Finance, Consulting/Strategy,
Ops/Analytics, HR):
- the **5 most relevant stories**, each with an original 2–3 line summary and a "why it matters for placements" line,
- a **5-question multiple-choice quiz** built from those stories, and
- a **Company of the Day** brief (business lines, recent news, likely interview talking points) for a company recruiting on campus.

Students sign in with their college email, read the brief, take the timed quiz, and compete on daily and weekly leaderboards.

## Where AI/ML is used

| Step | What the model does | How it's made reliable |
|---|---|---|
| **Classify and rank** (Claude Haiku 4.5) | Tags every headline to 0–2 career tracks and scores importance 1–5 | Batched in parallel; code then de-duplicates stories about the same event (LLM event labels + keyword-overlap check) |
| **Summarise and explain** (Claude Sonnet 4.6) | Writes original summaries and "why it matters" lines; rates each story's fit for the track | Prompted to use only facts in the source; full article text is never stored (copyright) |
| **Generate the quiz** (Claude Sonnet 4.6) | Writes MCQs with 4 options, the answer and an explanation, one per story shown | Forced JSON via tool use + a schema validator; one automatic retry with the validator's feedback; options are shuffled in code |
| **Company brief** (Claude Sonnet 4.6) | Segments, flagship brands, news, interview talking points | Optional admin-verified notes treated as ground truth; marked in the app as "AI-written, double-check" |
| **Human in the loop** | Admin page to review, edit and approve each day's drafts before 08:00 | Regeneration never overwrites approved or edited content |

Model choice came from side-by-side tests: Haiku alone was cheap but made factual slips in company briefs and wrote
easy-to-guess quiz options, so Haiku does the bulk tagging and Sonnet writes everything students read (~$0.30/day).
Bedrock capacity errors fall back automatically from the regional profile to the global one, then to the other model.

**Pilot:** 9 students signed up within the first day of a soft launch. Paused after the pilot to save cost; it can be redeployed in about 10 minutes.

**Tech:** Python 3.12, Amazon Bedrock (Claude Haiku 4.5, Sonnet 4.6, Converse API with tool use), AWS Lambda,
API Gateway, DynamoDB, Cognito, EventBridge Scheduler, S3 + CloudFront, AWS SAM; vanilla JS PWA with no framework or build step.

**Code map:** [backend/content/](backend/content/) (the AI pipeline: feeds, prompts, schemas, validation), [backend/api/app.py](backend/api/app.py) (quiz and leaderboard API),
[frontend/](frontend/) (the app), [samples/review.html](samples/review.html) (a generated day you can open in a browser), [template.yaml](template.yaml) (all infrastructure).

> **Status:** the AWS deployment was deleted after the pilot. Everything needed to bring it back is in this repo.
> AWS region is `ap-southeast-2` (Sydney) because the account's organization policy only allows that region;
> CloudFront serves the app from edge locations in India.

## Restart from scratch

Takes about 10 minutes. Everything is recreated from this folder.

1. Sign in to AWS: `aws login`
2. Deploy (creates the database, login, API, daily job and website, and prints the new app URL):
   ```bash
   ./deploy.sh
   ```
3. Bring back the company schedule and past daily content from the backup:
   ```bash
   .venv/bin/python scripts/restore_backup.py backups/table-2026-10-22.json
   ```
4. Recreate the budget alerts (they were deleted with the app). AWS Billing console → Budgets → Create budget →
   *Monthly cost budget* of $20, with email alerts at 25%, 50% and 100% to pgp25rajsrivastava@imt.ac.in.
   Untick "include credits" so the alerts track real spend.
5. Sign up in the app with your IMT email, then make yourself admin (the user pool ID is in the deploy output,
   or run `aws cloudformation describe-stacks --stack-name imt-pulse --region ap-southeast-2`):
   ```bash
   aws cognito-idp admin-add-user-to-group --region ap-southeast-2 --user-pool-id <NEW_POOL_ID> --username pgp25rajsrivastava@imt.ac.in --group-name admin
   ```
6. Share the new URL. **Everyone must sign up again.** Passwords can't be exported, so old accounts don't carry over.
   `backups/users-2026-10-22.json` lists who had signed up (9 students plus you) if you want to re-invite them.
7. Optional: to get today's content without waiting for 05:30 IST, use Admin → Review → **Generate now**.

What's in `backups/` (kept out of git because it contains student emails):
- `table-2026-10-22.json`: the full database (company schedule, daily content, profiles, scores, events).
- `users-2026-10-22.json`: the sign-up list (emails, dates).

If the SAM CLI is missing (e.g. the `.venv` folder was deleted): `python3 -m venv .venv && .venv/bin/pip install aws-sam-cli`.

## Architecture

```
Phone (PWA: vanilla HTML/CSS/JS, service worker)
  │  static files                         │  API calls (Cognito ID token)
  ▼                                       ▼
CloudFront ──► S3 (private bucket)     API Gateway HTTP API ──► ApiFunction (Python 3.12) ──► DynamoDB (1 table)
                                          ▲ JWT authorizer                                         ▲
Cognito user pool (email + password, code verification, pre-sign-up Lambda: @imt.ac.in only)     │
                                                                                                  │
EventBridge Scheduler 05:30 IST ──► GenerateFunction ──► RSS feeds + Amazon Bedrock ──────────────┘
                                     (Haiku 4.5 tags stories, Sonnet 4.6 writes summaries/quizzes/briefs)
```

- **Everything is in one SAM template**: [template.yaml](template.yaml). Pay-per-use only, so idle cost is close to zero.
- **Code**: [backend/api/app.py](backend/api/app.py) (all API routes), [backend/content/](backend/content/)
  (feeds, prompts, JSON validation, daily job), [backend/auth/presignup.py](backend/auth/presignup.py),
  [frontend/](frontend/) (the PWA).
- **Tracks**: Marketing, Finance, Consulting/Strategy, Ops/Analytics, HR (HR news comes mainly from ET HRWorld).
- **Data** (single DynamoDB table): daily content per track, Company of the Day, company schedule,
  user profiles, quiz attempts, analytics events (auto-expire after 180 days).
- **Publishing**: the job saves everything as *draft* at 05:30. Students see it from **08:00 IST** automatically.
  Whatever you edit or approve before then is what goes out, and a regeneration never overwrites your edits.
- **Quiz**: 5 track questions (one per story shown) + 2–3 Company of the Day questions, open 08:00–23:59 IST, one attempt per day.
  Answers are checked on the server and never sent to the phone in advance. Each question is timed on the
  server from the moment it is shown.
- **Scoring**: 10 points per correct answer + up to 3 speed points (full under 10s, zero at 40s).
  Streak multiplier: 1.1x at 3+ days in a row, 1.25x at 7+.
- **Copyright**: only headline, link, source and time are stored. Summaries are written by the model;
  every story links to the original.
- **Secrets**: none are needed (Bedrock uses the Lambda's IAM role). If a third-party key is ever added,
  put it in SSM Parameter Store as a SecureString, never in code or git.

## Deploy

Prerequisites: run `aws login` first (browser sign-in). The SAM CLI is installed in `.venv/`.

```bash
./deploy.sh
```

That validates the template, deploys the stack `imt-pulse`, writes `frontend/config.js` from the stack
outputs, uploads the web app to S3 and clears the CloudFront cache. Takes 1–3 minutes.

## Make someone an admin

Admins see the **Admin** tab (review drafts, schedule companies, stats). After the person has signed up:

```bash
aws cognito-idp admin-add-user-to-group --region ap-southeast-2 --user-pool-id <POOL_ID> --username pgp25rajsrivastava@imt.ac.in --group-name admin
```

They need to log out and back in once for the Admin tab to appear. The pool ID changes on every fresh deploy (see the stack outputs).

## Add companies (Company of the Day)

In the app: **Admin → Companies**.
- **Company name** and **also known as** (e.g. `HUL`) are used to find that day's news about it.
- **Feature it on** is the date it appears as Company of the Day; **process date** is shown to students.
- **Verified notes** (optional): 2–3 lines of facts you trust (segments, roles hiring). The AI treats these as
  ground truth, which is the best way to avoid wrong facts in the brief.

Schedule companies at least a day ahead (the brief is written at 05:30 IST). If you add or change today's
company after 05:30, go to **Review → Generate now**.

## Review the daily content

**Admin → Review** (defaults to today):
- Each section (Company + 5 tracks) shows *Draft / Approved / Edited* and any *Failed* or warning flag.
- Edit any summary, "why it matters", quiz question, option, correct answer or explanation. You can also remove a story.
- **Save & approve** locks a section, so later regenerations won't replace it.
- **Generate now** reruns the pipeline for that date in about 2 minutes. Tick the box to replace sections you edited too.
- "Left out by the pipeline" shows candidate stories that were dropped and why.

If a section shows **Failed**, the model returned invalid JSON twice. Press **Generate now** to retry,
or leave it: the rest of the day still works.

## Stats

**Admin → Stats**: daily active users, quizzes started/completed, stories opened, shares, sign-ups,
and the **day-7 return rate** (of users whose first day was 7+ days ago, the share who came back on day 7).

## Things to tell users

- Sign up with your `@imt.ac.in` email. **The verification code often lands in Outlook's Junk folder.**
- Cognito's built-in email sender is limited to about **50 emails per day** for the whole app
  (sign-up codes + password resets). That is enough for a 40–80 person pilot if sign-ups are spread over 2 days.
  If it runs out, codes stop arriving until the next day. The fix is switching to Amazon SES (not set up).
- Install it: open the link in Chrome (Android) → *Add to Home screen*, or Safari (iPhone) → Share → *Add to Home Screen*.
- The Company of the Day brief is AI-written. Double-check facts before an interview.

## Costs (pilot)

| Item | Approx. per month |
|---|---|
| Bedrock (Haiku tagging + Sonnet writing, ~$0.25–0.35/day) | $8–11 |
| Lambda, API Gateway, DynamoDB, S3, CloudFront, Cognito at 40–80 users | under $1 (mostly free tier) |
| **Total** | **~$9–12** |

Budget alerts (`IMT-Pulse-Pilot`) email pgp25rajsrivastava@imt.ac.in at $5, $10 and $20 of real spend.
To cut Bedrock cost by ~60%, deploy with Haiku for writing too:
`.venv/bin/sam deploy ... --parameter-overrides WriteModelId=au.anthropic.claude-haiku-4-5-20251001-v1:0`.

## Teardown (deletes everything)

```bash
./teardown.sh
```

Asks you to type `DELETE`, empties the web bucket, deletes the whole `imt-pulse` stack (users, scores, content,
app) and waits until it's gone. Two leftovers it tells you about: the SAM deploy bucket
(`aws-sam-cli-managed-default` stack) and the budget alert, both free or nearly free.

## Local tools

- `scripts/sample_day.py` generates one day's content locally (no database) into `samples/`. `scripts/render_review.py` turns it into a readable HTML page.
- `scripts/make_icons.py` redraws the app icons.

## Known limitations

- In a lot of questions the correct option is still the longest one. Fix individual questions on the Review page.
- Feeds sometimes carry several articles about one event. The pipeline removes most duplicates, but not all.
- If Bedrock's Australia profile is out of capacity, calls fall back to the global profile automatically.
- Content is generated once per day. Breaking news after 05:30 IST appears the next morning.
