# DOB clearability and confirmation-time boundary

AgeCheckResponse now returns clearable on the admin and parent lists and both recheck responses. It is true only for an open, unexpired hold whose recorded dates are no more than two calendar years apart and both inside the captured enrolled age band. Missing dates or an unavailable band return false. It does not mean school recheck or parent reconfirmation can be skipped. Resolved and expired checks return false; holdReasons and the existing recheck timestamps provide the remaining context. No parent DOB is added to staff responses.

Later parent consent submissions and school-date reconciliation cannot reopen an already matched or resolved activation check. The original confirmation remains an audit record. A new initial confirmation can still create a hold; a database user status of active alone is not proof DOB confirmation previously completed, because unconfirmed roster users also use that stored status.

Roster import was already made create-only in 5c713e4. Its former existing-student path could overwrite first name, last name and DOB, reconcile the DOB mismatch, and add a class enrolment. Matching existing pupils now return without those mutations. Matching is school plus admission number, case-insensitive.

Frankfurt is both the repository intention and the actual service region confirmed by Teslim on 21 October. No Oregon-to-Frankfurt migration is needed. Render deployment belongs to a different account, so this checkout cannot trigger or inspect its private deployments. Verify the public AgeCheckResponse schema contains clearable after deployment.

25 focused tests passed against the disposable local database. Production alembic upgrade head completed successfully; the existing latest revision is 20261020_0111 and this change requires no new schema migration.
