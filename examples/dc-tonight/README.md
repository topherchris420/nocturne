# A fictional first night

Every owner, permission, circuit load and observation in this directory is invented. No building or streetlight was changed.

The example contains two owner-ready actions (a facade switch and office blinds), one shop awaiting permission and one streetlight investigation draft. Its conditional estimate is **4.8 kWh** for the 600 W facade over eight hours; the blinds receive **no electricity credit**. All completion rows are deliberately blank.

Open `action-sheet.html` locally for the printable handoff. The calendar marks its events as fictional. For actual work, start fresh in `nocturne app --tonight`.

Reproduce into a new directory:

```bash
nocturne tonight --example --date 2026-10-15 --out regenerated-tonight
nocturne receipts regenerated-tonight/project.json regenerated-tonight/receipts.csv
```

The second command should exit 3: both owner-ready actions remain unconfirmed, with zero estimated completed benefit. See [the field guide](../../docs/TONIGHT.md).
