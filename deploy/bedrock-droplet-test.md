# Testing a Bedrock draft on the droplet

A Bedrock draft is written only from pages the analyst supplies for each piece (pasted with a URL and a date, or fetched from a site on the approved list). The tool looks for sources itself when a draft starts (it needs `EXA_API_KEY`), and the analyst can add more. Code checks that every quote is in the saved page word for word and that every figure in a claim is in its quote. Without `EXA_API_KEY` nothing is searched and a piece with no source comes back unavailable.

Times on screen are East Africa Time. Reports are named by week ending date.

## 1. What must be true first

- The pull request with the Bedrock work is merged into `main`.
- The **Publish images** run for that merge is green on the Actions tab, so `ghcr.io/clivemisiko/cytonn-weekly-api` and `cytonn-weekly-web` carry the new build.
- You can reach the app, either through the proxy's address or through an SSH tunnel (see `deploy/docker-compose.server.yml`): `ssh -L 8010:127.0.0.1:8010 -L 5173:127.0.0.1:5173 <deploy-user>@<production-host>`.
- AWS: Bedrock model access is enabled for the account in the region you will use, and the IAM user or token may call `bedrock:InvokeModel` on the inference profile and on the foundation models it routes to.

## 2. Lines to add or change in the server `.env`

Names only. The values are yours and never go into the repository, a chat or a log.

```
CYTONN_LLM_PROVIDER=bedrock
AWS_REGION=
BEDROCK_MODEL_ID=
```

Then credentials, one of these two:

```
AWS_BEARER_TOKEN_BEDROCK=
```

or

```
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=        # only for temporary keys
```

Notes:

- `BEDROCK_MODEL_ID` must be an **inference profile ID** such as `us.anthropic.claude-sonnet-4-6` (the default when the line is empty or absent), not a bare foundation model ID, and the profile must exist in `AWS_REGION` (`us-east-1` for the default profile). A prefix like `us.` goes with a US region.
- `CYTONN_LLM_MODEL` belongs to the Anthropic provider and is ignored here. Only `BEDROCK_MODEL_ID` chooses the Bedrock model.
- If both a bearer token and an access key pair are set, the bearer token is used.
- `EXA_API_KEY` and the `CYTONN_LOCAL_*` settings are ignored on this path.

## 3. Deploy and apply

```sh
cd ~/cytonn-weekly
./deploy.sh
```

`./deploy.sh` pulls the images and recreates `api` and `web`. After **any** `.env` edit the api must be recreated, because `env_file` is read only when the container is created. A restart is not enough:

```sh
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --force-recreate api
```

(Use `deploy/docker-compose.server.yml` as the second file if the folder is a clone and the file is not beside `docker-compose.yml`.)

Read the startup line:

```sh
docker compose -f docker-compose.yml -f docker-compose.server.yml logs --tail 50 api | grep "Drafting with Amazon Bedrock"
```

It should read like this (names only, never a value):

```
Drafting with Amazon Bedrock, model us.anthropic.claude-sonnet-4-6 (from the default, BEDROCK_MODEL_ID is not set). AWS variables set: AWS_REGION, AWS_BEARER_TOKEN_BEDROCK; not set: AWS_DEFAULT_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN.
```

Check three things in it: the model is the one you meant, "(from BEDROCK_MODEL_ID)" appears if you set it, and the credential you intended is under "set". If it also says `CYTONN_LLM_MODEL is set and is ignored on this path`, that is only a reminder. If there is no such line at all, the provider is not bedrock: check `CYTONN_LLM_PROVIDER` and recreate the api.

## 4. Smoke test, in order

Spend as little as possible: a piece with no sources makes no Bedrock call at all, so supply sources for exactly one piece and the draft makes one call.

1. Open the overview through the tunnel. The side rail must say **Production · bedrock** and there must be **no DEV MODE ribbon** anywhere. A DEV ribbon means the provider is the local one.
2. Pick the cheapest piece: **Real Estate** (weekly, the default week), piece **Affordable housing**. Its draft makes one Bedrock request for each piece that has sources, and nothing else. (The next cheapest is **Digital Payments**, piece **Visa**, which adds one request for the closing outlook.)
3. Open Real Estate's start screen. The **Sources** panel lists six pieces. Every piece except the one you will use shows "Sources are found automatically when you draft."; leave them so.
4. For **Affordable housing** supply three sources:
   - two pasted: open "Add a source", give the page's address, the page's date and its text (copy the article text as it is, nothing edited), then "Save pasted text";
   - one fetched: paste an address on an approved site (the panel lists them under "Approved sites") into "Address (URL) to fetch" and press "Fetch page". If the page has its date in a meta tag it is filled in; if the sentence says the date could not be read, use the paste form for that page instead.
   Each source should show its host, date, characters, whether it was pasted or fetched, a fingerprint and a "View saved text" link. Open the link once: the text must be what you gave.
5. Press Draft. With no `EXA_API_KEY` on the server nothing is searched and no confirmation is asked (it names only pieces a search already found nothing for). Only the one piece is written; the others come back unavailable with "No sources were supplied for this piece, so nothing was drafted."
6. In the review, expand the drafted claims. Each one shows its source host, the page's date, the quote in quotation marks and "checked word for word against the saved text", the fingerprint and "View saved text". Confirm the quote is really in the page you gave. A pasted page from a host off the list carries "host not on the approved list".
7. Check the fingerprint: it is the sha256 of what is stored. On the server, for a pasted source (`.txt`) or a fetched one (`.html` or `.pdf`, the page as received):

   ```sh
   sha256sum backend/data/inputs/sources/<week ending date>/<source id>.*
   ```

   The first eight characters must equal the fingerprint on screen. The source id is the one in the "View saved text" link.
8. Check that a changed page is refused and a claim that is not in its page is dropped:
   - **Changed page.** Edit the saved text of a source you do not need again (change one word in `<source id>.txt`) and draft again. The Sources panel and the draft both refuse that source with "The saved copy of <host> (<source id>) no longer matches the fingerprint taken when it was saved, so it was not used. Remove it and add it again." Remove it in the panel afterwards.
   - **Dropped claim.** The model quotes pages itself, so a bad quote cannot be ordered on demand. What you can check live is that the claim list in the review holds only claims whose quote you can find in the page, and that when the model did give a quote that is not in the page, or a figure that is not in its quote, the piece's warnings say "claim dropped" with the reason. A piece whose every claim was dropped comes back unavailable with "No claim in the draft held up against the supplied sources". The tests that force each case are `backend/tests/test_sourced_claims.py` and the Playwright spec `T113`, which reads the dropped claim's warning from the saved review.
9. Read the count of requests and tokens (section 7), then stop. Do not draft the other sections.

## 5. The sentences you may see

They are fixed sentences. None holds a secret or the library's own text. Each ends the draft; the log has one more line with the error class.

| Sentence starts | Meaning | What to do |
| --- | --- | --- |
| "Drafting with Amazon Bedrock needs an AWS region, and none is set." | `AWS_REGION` (or `AWS_DEFAULT_REGION`) is empty. Shown before a draft starts. | Set `AWS_REGION`, recreate the api. |
| "Drafting with Amazon Bedrock needs AWS credentials, and none are set." | Neither a bearer token nor the key pair is set. A role on the host is not looked for. | Set one, recreate the api. |
| "Amazon Bedrock did not accept the AWS credentials." | Wrong key, wrong token, or credentials for another region. | Check the variables the sentence names, recreate the api. |
| "The AWS credentials have expired" | A session token or bearer token ran out. | Put fresh ones in `.env`, recreate the api. Drafting again will not help before that. |
| "Amazon Bedrock refused the request (AccessDeniedException)." | Model access is not enabled in that region, or the IAM policy does not allow `bedrock:InvokeModel` on the inference profile and the foundation models behind it. | Enable the model in the Bedrock console and fix the policy. |
| "Amazon Bedrock did not accept the request (ValidationException)." | Usually the model ID. | Make `BEDROCK_MODEL_ID` an inference profile ID that exists in `AWS_REGION`, recreate the api. |
| "Amazon Bedrock is throttling this account (ThrottlingException)" | Too many requests or tokens just now. | Wait a few minutes and draft again, or ask AWS for a higher quota. |
| "Amazon Bedrock says a service quota ... has been reached" | A quota is used up. | Wait for it to reset or ask AWS to raise it. |
| "Amazon Bedrock could not serve ... just now" | A server side error or timeout. | Draft again in a few minutes. |
| "This server could not reach Amazon Bedrock" | Network error or timeout from the droplet. | Check the droplet's network. |
| "Signing Bedrock requests with access keys needs boto3" | The image lacks boto3 and you used keys. | Use `AWS_BEARER_TOKEN_BEDROCK`, or rebuild the image with boto3. |
| "Amazon Bedrock does not propose section titles" (Focus) | Bedrock has nothing to search, so a Focus needs its titles typed. | Type them under Sections. |
| "No claim in the draft held up against the supplied sources" | Every claim failed its quote or figure check, so nothing was kept. Each failure is in the piece's warnings. | Check the pages, or supply others. |
| "No sources were supplied for this piece, so nothing was drafted." | The piece has no saved source. | Supply a page, draft again. |

## 6. Rollback

Back to the last build that worked, by its commit (from the Actions tab or `git log`):

```sh
./deploy.sh sha-abc1234
```

That tag stays in use until the next `./deploy.sh` with no argument, which goes back to `latest`.

To go back to the Anthropic provider with no new build, change `.env` alone: set `CYTONN_LLM_PROVIDER=anthropic` (or delete the line, which means the same), make sure `ANTHROPIC_API_KEY` is set, then recreate the api:

```sh
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --force-recreate api
```

The Bedrock lines can stay in `.env`; they are ignored on the Anthropic path. Reviews already saved keep their `drafted_by` (`bedrock:<model>`).

## 7. Reading what a run used

Every Bedrock request writes one line to the api log with its number, the model, the input and output token counts and the stop reason. Counts only, never text:

```sh
docker compose -f docker-compose.yml -f docker-compose.server.yml logs --since 15m api | grep "Bedrock request"
```

Count the lines for the run. For a Focus the review also shows "API requests" for the draft. The token totals are the sum of the lines. The tool does not price anything: take the pricing from the AWS console, and check usage there under CloudWatch metrics for Bedrock (invocations, input and output token counts) for the same model and region.

A stop reason of `max_tokens` means that reply was cut off and was discarded; the piece comes back with a warning that the model returned invalid JSON.
