# Lesson sources for exercising the parse

Real lesson documents, kept here so the content pipeline can be run end to end
against something that reaches every part of it.

Each lesson is a pair:

- `<name>.md` — the source, because that is what a person can read and edit in
  a diff
- `<name>.docx` — what actually gets uploaded, since that is the shape a
  teacher's lesson arrives in

The .docx is generated from the .md. After editing the source, rebuild it:

    python scripts/build_lesson_docx.py tests/fixtures/lessons/*.md

`tests/content_parsing/test_lesson_fixtures.py` fails if you forget, and also
if an edit strips out something a modality depends on.

## simple-interest-jss3

Written to force all five modalities out of the parser. Calculation is the one
that matters: it only appears when the source carries arithmetic the model can
decompose into co-construction steps, and no lesson in the live library has
ever produced one. The two worked examples with their numbered steps are there
for that, the rectangle-in-bands passage is there to earn a diagram, and the
practice questions are there for the interactive variant.

## Running one through

Sign in, then upload the .docx the way a teacher would:

    API=https://api.nevolearning.com
    TOKEN=$(curl -s -X POST "$API/api/v1/auth/login" \
      -H 'content-type: application/json' \
      -d "{\"method\":\"password\",\"email\":\"teacher.demo@nevolearning.com\",\"password\":\"$TEACHER_PASSWORD\"}" \
      | jq -r .access_token)

    curl -s -X POST "$API/api/content/upload" \
      -H "Authorization: Bearer $TOKEN" \
      -F "file=@tests/fixtures/lessons/simple-interest-jss3.docx"

The 202 carries `lessonId` and a `pollUrl`. Poll it until the status leaves
`processing`:

    curl -s "$API/api/content/parse-runs/$PARSE_RUN_ID" \
      -H "Authorization: Bearer $TOKEN" | jq

What to check on the finished lesson:

- `fallbackSegmentCount` is 0, meaning the model wrote it rather than the
  deterministic splitter
- a segment with `contentType: "calculation"` whose `calculationVariant` has a
  populated `answer`
- `visualVariant` present on the diagram segment
- `recap` and `assessment` present on the lesson

Image generation needs credit on the OpenAI account. Without it every picture
fails with a 429 carrying `credit_balance_exhausted`, which the run's review
notes will say in as many words.
