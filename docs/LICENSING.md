# Hardstop Licensing Strategy

_Last updated: December 29, 2025_

## Goals
- Preserve WhatsYourWhy's ability to monetize Hardstop through hosted services,
  support retainers, or commercial embeddings.
- Keep the codebase inspectable and extensible for contributors.
- Allow hobbyists, researchers, and prospects to evaluate Hardstop locally
  without negotiating upfront contracts.
- Provide a clear, time-bound path toward a more permissive license to build
  community trust.

## License Selection
Hardstop now ships under the **Hardstop Business License (SBL-1.0)**, a custom
license derived from permissive terms with explicit restrictions around
Commercial Use. Key attributes:

- **Non-commercial freedom:** Individuals and teams can clone, modify, and run
  Hardstop indefinitely for evaluation, research, or personal workflows.
- **Commercial gate:** Any production deployment that supports revenue,
  customer-facing services, or fee-based insights requires a commercial
  agreement with WhatsYourWhy, Inc.
- **Small production trial allowance:** Up to three internal users may run
  Hardstop in production solely to validate fit prior to signing a contract.
- **Future open path:** On **January 1, 2029** this version of the codebase
  automatically becomes available under Apache 2.0, protecting long-term
  adopters and encouraging contributions.
- **Contribution alignment:** All inbound contributions can be relicensed by
  the company, enabling future dual-licensing or proprietary add-ons.

## Recommended Monetization Paths
1. **Commercial License / Support Agreements**
   - Offer annual or usage-based licenses for production deployments, managed
     hosting, or agent-backed workflows.
   - Bundle priority support, roadmap influence, or private modules.

2. **Hosted Hardstop (SaaS)**
   - Operate a managed Hardstop environment under proprietary terms. The SBL
     ensures third parties cannot legally run a competing hosted service.

3. **Premium Modules**
   - Keep paid adapters, correlation heuristics, or enterprise governance
     modules proprietary while relying on the SBL guardrails for the core.

4. **Partner Integrations**
   - Require OEM/partner agreements when logistics or risk platforms want to
     embed Hardstop outputs into their products.

## Compliance Guidance
- Point all public references (README, marketing) to the SBL and contact
  address `licensing@whatsyourwhy.com`.
- Maintain a changelog of versions and their eventual Change Date so downstream
  users know when Apache 2.0 applies.
- Capture written consent before granting any rights broader than SBL-1.0.
- Encourage community forks for research/testing; politely redirect
  commercialization requests to the licensing channel.

## Future Considerations
- Evaluate whether the next major release should extend the Change Date or
  adopt an off-the-shelf license (e.g., Business Source License 1.1,
  Polyform Shield) for even clearer comparability.
- Consider dual-licensing (SBL + commercial EULA) once paying customers are
  onboarded.
- Document pricing tiers and approval workflows to keep licensing responses
  predictable as interest grows.
