# Director browser QA, 2026-11-02

This is browser fixture evidence only. It does not establish backend orchestration, media inspection accuracy, or database concurrency. Backend/API/PostgreSQL validation is tracked separately.

The frontend was built with `NEXT_PUBLIC_DEMO_MODE=true` and `NEXT_DIST_DIR=.next-director-demo-qa`, then served only at `http://127.0.0.1:3118`. gstack `/browse` used a dedicated browser state under `.tmp/director-ui-browser`.

Verified in the current presentation demo:

- Initial Milo script exposes the existing `Process Approval` button. There is no second `Approve narration` button.
- Clicking that initial sign-off starts autonomous fixture progress. The director reaches `Master ready for your review`, with Scene 1, Scene 2 and Scene 3 verified, without another human action.
- No scene approval button exists during initial or completed progress.
- At a 390 × 844 viewport, document/body widths are 390 pixels. There is no horizontal overflow. The mobile progress screenshot was inspected visually.

The presentation demo currently emits a legacy `vea_artifact` final draft, so its final feed shows existing Vea controls and does not exercise the new canonical `director_artifact` card. The demo runtime was not changed. To inspect the new card, a separately labelled browser fixture rendered the actual `HitlCard` component with a standalone `director_artifact` and simulated inspection evidence. That fixture displayed the playable local video, “Milo recommends approval · automated checks passed”, `Approve final master`, `Reject`, and the storyboard edit link. Opening `Master inspection report` exposed the supplied evidence. Its mobile width was also 390 pixels with no horizontal overflow; screenshot inspected visually. This static fixture does not claim to test live final-decision mutation routing, which is covered by API/component tests.

Screenshots and the fixture generator are local validation artifacts under `.tmp/director-ui-browser/`:

- `mobile-milo.png`
- `mobile-director-master.png`
- `director-master-fixture.html`

The strict demo CSP prevented the development build from hydrating; the production-mode demo hydrated and passed the checks above. Both the demo production build and the normal production build succeeded. The loopback frontend and dedicated browser server were stopped after QA. Next's temporary generated TypeScript include entries were removed.
