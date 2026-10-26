# HARDSTOP licensing entity audit

Audit date: October 26, 2026
Audited upstream commit: `89bb4478d1a523a43d9f910182979f67db4c5caf`
Scope: current tracked text files on `WhatsYourWhy/Hardstop` main.

## Approved source and authorization

The HARDSTOP Commercial Packaging State, updated October 26, 2026 after Sprint 8 (internal approved source)
identifies Shank Strategy Ops LLC as the controlling and sole legal entity.
It identifies WhatsYourWhy as a non-corporate developer/GitHub handle.

Its Gate 9 row records **Pass**, citing
`SSO-HS-GATE09-v1.0`
(`hardstop_gate_09_licensing_and_pilot_agreement.md`), and states that Justin
Shank approved the entity alignment and locked 30-day bounded pilot agreement
in Sprint 1.

The repository owner requested an audit and reconciliation to that approved
entity while preserving existing licensing rights and restrictions. This
correction implements that existing entity decision. It does not approve new
commercial or legal terms.

## Conflict inventory and exact disposition

Line numbers below refer to the audited upstream commit.

| File / location | Finding | Correction |
| --- | --- | --- |
| LICENSE:7, Section 1.1 | Company is defined as `WhatsYourWhy, Inc.`, conflicting with both the approved entity and LICENSE:4's existing Shank Strategy Ops LLC copyright notice. | Replace only the defined entity with `Shank Strategy Ops LLC`. All downstream uses of the defined term Company then refer to the approved entity. |
| README.md:107 | The commercial agreement names `WhatsYourWhy, Inc.`. Its blanket production-use summary also omits Section 2.2's limited evaluation exception. | Name Shank Strategy Ops LLC, identify WhatsYourWhy as the handle, tie the agreement requirement to defined Commercial Use, and state all of Section 2.2's conditions. |
| docs/LICENSING.md:6-7 | The monetization goal attributes commercial rights to `WhatsYourWhy's` without separating handle from legal entity. | Replace the old strategy framing with an explicit Shank Strategy Ops LLC licensor/contracting-party statement and a separate developer-handle explanation. |
| docs/LICENSING.md:21-23 | The commercial gate again names `WhatsYourWhy, Inc.`. | Require the separate written agreement with Shank Strategy Ops LLC, subject to LICENSE. |
| docs/LICENSING.md:51-52 | Public inquiries are routed to `licensing@whatsyourwhy.com`, inconsistent with LICENSE's existing contact. No evidence was located confirming that mailbox. | Reuse LICENSE's existing repository route and `shankstrategy@gmail.com`. Mailbox delivery was not tested. |
| docs/LICENSING.md:3, 18-30, 32-66 | December 2025 strategy is presented as current. The trial summary omits load/evaluation purposes and the no-sale/barter/revenue conditions. Hosted SaaS recommendations conflict with the current local-first product baseline, and alternative-license/pricing suggestions are unresolved strategy. | Date the corrected summary October 26, 2026; summarize the existing license faithfully; identify old options as superseded strategy rather than current features, terms, or commitments; point to the approved Gate 9 artifact without inventing its contents. |

No other conflicting entity references were found in the 131 tracked text
files scanned. The single tracked PNG was outside the text scan. The
`buy_me_a_coffee: WhatsYourWhy85` value in .github/FUNDING.yml is a funding
handle, not a Company definition or contracting-party statement, and is
unchanged. GitHub namespace/URL references also retain the developer handle.

## Preserved operative terms

LICENSE differs from the audited upstream file by exactly one replacement:
`WhatsYourWhy, Inc.` to `Shank Strategy Ops LLC` in Section 1.1. Its
copyright already named the approved entity and remains unchanged.

The license identifier SBL-1.0, Version 1.0 / January 17, 2026 date, 2025
copyright year, Sections 1.2-11.1, and contact text remain unchanged. This
preserves the existing non-commercial grant, three-internal-user evaluation
conditions, commercial restrictions, redistribution and contribution terms,
patent/trademark limits, disclaimer, liability limitation, termination,
January 1, 2029 Apache availability, and Delaware governing law.

Clarifying those existing terms in the public summaries does not add a
production entitlement, support promise, fee schedule, or pilot contract.

## Gate 9 verification and limits

| Check | Result |
| --- | --- |
| Approved entity decision | Verified directly in the October 26 packaging state. |
| Public entity alignment before correction | Failed: the three public files contradicted the recorded alignment. |
| Public entity alignment in this corrected revision | LICENSE, README, and licensing documentation consistently name Shank Strategy Ops LLC; WhatsYourWhy is identified as a handle. |
| Gate 9 recorded status | The source records Pass. This audit reconciles its entity-alignment statement with the corrected repository revision and does not change or reapprove the recorded gate. |
| Deployment of the correction | The public main branch is reconciled only once the correction is merged. A proposed branch alone does not repair main. |
| Locked pilot agreement | The packaging state names and records approval of the artifact, but its complete text was not located in the repository or connected Drive/Library searches. Its contents, signature readiness, and consistency with LICENSE were not independently verified. |

The entity portion of the recorded Pass is supported by the corrected
revision. The recorded pilot approval is source evidence, not an independent
legal or full-contract validation by this audit.

The package version is separately `1.2.0` in pyproject.toml, while the
packaging state describes v1.1 and a v0.3.0-to-v1.1.0 Gate 7 patch specification.
That separate release-baseline discrepancy is outside this entity correction;
no runtime or package version was changed.

## Professional legal review items

These are review questions, not findings of invalidity. No legal terms below
were edited.

- **Entity correction and prior dealings:** Confirm the LLC's ownership and
  authority to license the code and contributions. Determine whether prior
  downloads, contributions, or signed agreements naming the old entity need
  notice, consent, amendment, or assignment. A repository edit does not itself
  document a transfer or amend an executed agreement.
- **Use boundaries and pilot fit (Sections 1.3, 1.4, 2.1, 2.2, 3):** Review the
  non-commercial/commercial definitions, revenue-workflow boundary,
  non-transferable grant alongside redistribution permission, and the
  three-internal-user exception against the separate 30-day pilot agreement.
  Section 2.2 itself does not impose a 30-day duration; none was added.
- **Contribution, patent, and trademark terms (Sections 5-6):** Confirm the
  intended scope of contribution relicensing rights and the treatment of
  earlier submissions, patent rights, and use of marks.
- **Disclaimer, liability, and termination (Sections 7-9):** Review the
  disclaimer, liability exclusions, automatic termination/destruction duty,
  and survival language against the intended commercial/pilot contract.
- **Future license transition (Section 10):** Confirm which releases and
  derivatives are covered by "this version" and how Apache 2.0 availability on
  January 1, 2029 will be published. That date and promise are unchanged.
- **Governing law (Section 11):** Confirm whether Delaware is intentional.
  The approved entity's Indiana location alone does not authorize replacing
  the chosen law.

Any resulting change to rights, restrictions, dates, governing law, support
commitments, or pilot obligations requires a separate authorized decision.
