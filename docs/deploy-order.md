# Backend/client deploy order

A stricter backend validation must not go live before the client sends the format it requires.

For a contract change, first publish an additive backend shape that accepts both old and new client payloads. Deploy the client and verify it sends the new shape in production. Only then deploy the stricter backend validation. Keep the old form accepted until the deployed client population has moved; document the removal separately.

For feature flags, deploy the inactive backend route and schema first, complete device/browser verification, then enable dependent collection or behaviour. A successful code deploy alone does not mean a feature is enabled.
