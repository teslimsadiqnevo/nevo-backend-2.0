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

## The library

| lesson | subject | what it is for |
|---|---|---|
| `simple-interest-jss3` | JSS 3 Maths | The only one written to force a calculation variant. Two worked examples of five numbered steps each, so the model has something it can decompose into co-construction; a rectangle-in-bands passage to earn a diagram. |
| `linear-equations-jss3` | JSS 3 Maths | Algebra rather than arithmetic, and a second calculation source with a different shape - three worked examples including one with the unknown on both sides, and a word problem turned into an equation. |
| `photosynthesis-jss2` | JSS 2 Basic Science | Not maths at all. A labelled cross-section described in prose for the visual, a five-step practical for procedure, and a word equation rather than a numeric one. |
| `paragraph-writing-jss1` | JSS 1 English | Prose about prose, with a good and a bad worked example side by side. The hardest for a parser: no numbers anywhere and the diagram is a shape, not an object. |

Between them they cover three subjects, three year groups, and the four
content types the parser can emit.

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
