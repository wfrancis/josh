# Material Quotes Email Center - Staging Test

## Result

**PASS for the staging pilot. Production was not touched.**

Tested site: `https://si-bid-stg-20260714-c0fa.fly.dev`

Tested code:

- Commit: `a2147d7bdc8fc60c54a4acf81dda6717463eb083`
- Tag: `material-quotes-hub-e2e-racefix-20260727`
- Environment: `staging`

## What We Proved With Real Email

We connected `willfrancis@standardinteriors.com` to the staging site and used
`wbfranci@gmail.com` as the fake vendor.

1. Alpha and Beta were prepared as separate bids.
2. Each bid made its own vendor email draft.
3. One click sent each request through Outlook.
4. Gmail received both requests.
5. Gmail replied to both requests with different CSV quote files.
6. Outlook sync matched each reply to the correct bid.
7. The exact item codes and units were checked before pricing.
8. Alpha received only Alpha prices.
9. Beta received only Beta prices.
10. Both requests became Complete.
11. All scheduled follow-ups stopped after the replies.
12. Sent emails, replies, attachments, dates, and SHA-256 hashes were saved.

Applied prices:

| Bid | Material | Price |
| --- | --- | ---: |
| Alpha | `ALPHA-LVT-101` | $2.45/SF |
| Alpha | `COMMON-TRIM-900` | $4.10/LF |
| Beta | `BETA-CPT-202` | $18.75/SY |
| Beta | `COMMON-TRIM-900` | $4.25/LF |

## Bug Found And Fixed

Alpha's reply arrived before Microsoft finished exposing the sent-email receipt.
The first sync could not safely connect the reply to the bid.

The fix now does two things:

1. Syncs Sent Items before reading vendor replies.
2. Rechecks an unresolved reply when its sent-email proof becomes available.

After deployment, Alpha repaired itself automatically. No manual assignment and
no second vendor reply were needed.

## Automated Safety Proof

The deployed harness passed **18/18 release checks**.

The fake mailbox passed **34/34 production-rule checks**. These include:

- Changed subjects and Outlook conversation matching.
- Ambiguous standalone email going to Needs Matching.
- Wrong units requiring review instead of changing a price.
- Duplicate replies and repeated syncs staying idempotent.
- Stale bid materials blocking sends and follow-ups.
- Send failures staying retryable without duplicate requests.
- Two follow-ups firing once each, then stopping.
- Assignment races not changing the wrong bid.
- Safe Test making no change to the real bid.
- Zero OpenAI calls for matching, parsing, pricing, or follow-ups.

The full machine-readable result is in `final-harness.json`.

## Restart Proof

Fly machine `784443eadd64d8` restarted at `2026-07-27T18:35:17Z`.

After restart:

- Both complete requests still existed.
- All four applied prices were unchanged.
- Both sent `.eml` files still matched their saved hashes.
- Both reply `.eml` files still matched their saved hashes.
- Both CSV attachments still matched their saved hashes.
- The Email Center still showed the saved proof and cancelled follow-ups.

Exact values are in `restart-proof.json`.

## Browser Check

Chrome checked the deployed Email Center at desktop and phone sizes.

- Outlook status, bid filter, tabs, proof links, attachments, and follow-up
  states were readable.
- No browser warnings or errors were recorded.
- The phone layout had no overlapping text or controls.

Screenshots:

- `01-both-requests-sent.jpg`
- `02-direct-replies-complete.jpg`
- `03-after-restart-complete.jpg`
- `04-mobile-complete.jpg`

## Honest Limit

Changed-subject, standalone, ambiguous, and wrong-unit cases passed through the
isolated fake mailbox using the same production matching and pricing functions.
They were not all sent as extra real Gmail messages because Gmail's browser page
became unreliable during that part of the test.

This does not hide a failure: the real Outlook send, real Gmail reply, real
attachment, exact matching, price write, automatic repair, and restart paths
were all completed.

## Cleanup

- Gamma and Delta safety requests were cancelled.
- Their four future follow-ups were cancelled.
- The staging Outlook connection and token were deleted.
- No further test email can be sent until Outlook is connected again.
