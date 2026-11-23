# Illustration spec
**22 November 2026.** Lives in the design system beside the palette and the radius scale. Sent with every image request.

## The split: what is depicted, and what Nevo adds

**Depicted subjects are in their own true colours.** Veins, flames, litmus paper, fruit, flags, minerals, tissue, apparatus. The picture is teaching a child what the thing looks like, and a wrong colour either teaches them something false or makes the real thing harder to recognise later. If the lesson used a photograph nobody would recolour it, and a drawing of the same subject is the same category. The four-colour rule governs interface surfaces, not content.

**Everything Nevo adds around the subject stays in the four.** Backgrounds, frames, arrows, brackets, callout rings, highlight bands and any annotation layer are chrome, they are ours, and they carry the house palette: Navy `#3b3f6e`, Cream `#f7f1e6`, Cream Elevated `#ede8dc`, Soft Violet `#9a9ccb`.

## Treatment, locked

Consistency comes from treatment rather than from palette. Six pictures of six different subjects in their own real colours still read as one set when every one of them is drawn the same way.

1. One aspect ratio: 3:2, filling the reading column (D195).
2. One internal margin, set once on the first set and used by every image after it.
3. One line weight, set the same way.
4. No shadows and no implied light source.
5. No gradients.
6. Flat rendering. Never photorealistic.
7. Plain ground. No scenery, no texture, no decorative background.
8. No generated lettering of any kind.

## Lettering

No text is ever generated into an image. Axis labels, part names, units, numbers and captions are laid over the picture in the page by the front end, in the product font. That is where the mangled lettering comes from every time, and it is also why layered labels are better: they are correct, selectable, scalable and translatable.

Every prompt carries an explicit instruction that the image contains no text, no letters, no numerals and no watermark.

## Telling things apart

Parts of a diagram are distinguished by shape, position and label, never by hue. This is the same rule that made the oldest-band Stroop a word-direction conflict and made the 2A icons differ by shape: four colours cannot carry colour-coded meaning legibly, so nothing is asked to.

The exception is the one above. Where the real colour of the subject is itself the information being taught, the real colour is used and the distinction is allowed to be chromatic, because that is the content rather than a coding scheme.

## What goes in every request

The style block above, verbatim, appended to the subject description. Not paraphrased per image, not rewritten per lesson. The test is simple: two images from the same lesson, opened side by side, should be obviously from the same product.
