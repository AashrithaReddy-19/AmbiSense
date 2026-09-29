# Demo guide

A 10-minute walkthrough that uses **no real people**. Use a synthetic or consented video and keep `DEMO_MODE=false` unless
you specifically want simulated numbers (they are labelled DEMO and kept apart from real data).

## Script

1. **Start** `.\start_all.ps1`; open the dashboard. Point out the *Privacy and responsible use* notice and the *Development mode* badge.
2. **Upload** a short MP4 on *Upload & Process* (choose classroom and activity context). Watch the status steps; note the file checks.
3. **Sessions**: filter by status, date range and *minimum coverage*; the URL updates, so the view is shareable. Select two sessions.
4. **Session Details**: walk the tabs with the keyboard (←/→). *Overview*: metrics with coverage/confidence and a genuine zero vs "Unavailable — reason". *Timeline*: events and the table alternative. *Quality & Evidence*: the per-metric evidence table, frame quality, optional-audio state. *Regions*, *Artifacts* (downloads), *Notes* (author, role, edited).
5. **Analytics**: choose a metric, coverage ≥ 50 %, Apply. Show gaps vs values and the 10-column table; open *Metric definitions*.
6. **Compare**: add two sessions; show compatibility notices, coverage/confidence/valid-observation charts, event frequencies, and that regions are compared only when layouts match.
7. **Reports**: filter, open *Details* (methodology, limitations, downloads), download a PDF (a second click while it runs is ignored). Retry a failed job.
8. **Search**: click *Find failed processing jobs.* and read *How your question was interpreted* (applied vs not applied).
9. **Classroom Setup**: draw a polygon, try a self-crossing one (blocked with a reason), undo/redo, zoom, move with the arrow keys, save a new version.
10. **Management / Settings**: roles, feature-access matrix, a risky threshold change (confirmation + audit), retention preview.
11. **Themes**: switch light/dark/system.

## Manual browser checklist (not automated)

- [ ] Camera permission prompt and live frames on the Live page (needs a real camera).
- [ ] 360 / 768 / 1024 / 1440 px wide: navigation becomes a drawer, tables become cards, tabs scroll, filters wrap; no horizontal page scroll.
- [ ] Keyboard only: skip link, tab order, arrow keys in tabs, focus trapped in dialogs and returned on close, Escape closes.
- [ ] Screen reader: chart summaries, table captions, live regions announce loading and results.
- [ ] Reduced-motion setting removes skeleton and spinner animation.
- [ ] Dark theme contrast on badges, banners and charts.
