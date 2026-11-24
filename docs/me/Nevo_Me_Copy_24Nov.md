# Nevo /me, approved copy

24 November 2026. Every learner-facing and guardian-facing string on the /me route. Approved for build. Square brackets are filled at runtime.

Voice: plain, second person, calm. No fragments. No em dashes. Never alarming on a refusal, never scolding on a delay, and the learner is never made to feel they did something wrong by something Nevo did.

---

## Identity

**Verification email**

Subject: Your Nevo verification code

Hello [first name], your Nevo verification code is [code]. It works for the next 30 minutes. If you did not sign up for Nevo, you can ignore this email and nothing will happen.

---

## Guardian consent

**Guardian email**

Subject: [Learner's first name] needs your consent to use Nevo

Hello,

[Learner's first name] has named you as their parent or guardian. They want to use Nevo to study their own course material, and because they are under 18 we need your consent before they can upload anything.

Nevo teaches a lesson to one learner at a time, adapting the level, pace and format as it reads how they are working.

You do not need to create an account. The page below explains what Nevo does with their work and asks you to agree to it.

Button: Read and give consent

If you were not expecting this, you can ignore this email and [learner's first name] will not be able to upload anything.

**Guardian consent page**

Heading: [Learner's first name] would like to use Nevo

Nevo teaches a lesson to one learner at a time, adapting the level, pace and format as it reads how they are working. [First name] uploads the material they are studying and Nevo teaches it to them.

Tick one: I agree to [first name] using Nevo to study their own course material.

Tick two: I agree to their material being sent outside Nigeria so that Nevo can prepare their lessons.

Fields: Your name. Your email. Your relationship to [first name].

Button: Give consent

Two separate ticks, never bundled. A guardian is agreeing on behalf of someone else, so each thing has to be separately visible or the single tick means nothing.

**The guardian field at sign-up**

Appears inline beneath the date of birth when the declared age is under 18. Never a refusal page and never a separate step.

Label: Your parent or guardian's email

Because you are under 18, a parent or guardian needs to agree before you can upload your own material. Enter their email and we will send them a short page to read. You can start using Nevo straight away while you wait.

**The waiting screen**

We have sent [guardian email] a page to read and agree to. You can take your onboarding and look around while you wait. Uploading your own material is the one thing that needs their consent first.

Actions: Send it again. Use a different email.

**The 14-day message**

Replaces the waiting screen after fourteen days without an answer. The actions do not change.

Your guardian has not answered yet. You can send it again, or use a different email if that one was wrong. Everything you have done so far is saved, and uploading will open as soon as they agree.

---

## Upload refusals

Two distinct codes, never collapsed into one.

**Consent outstanding**

Uploading opens once your guardian agrees. We sent [guardian email] a page to read, and you can send it again from here.

**Allowance used, lower tier**

You have used all [n] of your lessons for this month. They reset on [date]. If you need more before then, [tier name] gives you [n] lessons a month.

Button: See the tiers

**Allowance used, top tier**

You have used all 25 of your lessons for this month. They reset on [date]. If you need more than 25 a month, tell us what you are working on and we will find a way.

Button: Get in touch

Routes to the enquiry endpoint, which is also where a lesson teacher or a tutorial centre lands.

---

## Progress

**Locked progress screen**

Returned as a 200 with a locked body, never a 403. This is a product state, not a fault.

Nevo is already following how your mastery is building across every concept you have worked on. The ₦2,499 tier shows you that: which of the three levels you have reached on each concept, how it has moved over the last 90 days, and what is ready for a return.

Button: See what's included

No score, no percentage, no grade, no numbered bar anywhere on this surface or behind it.

---

## Billing

**Renewal reminder, seven days before**

Subject: Your Nevo month ends on [date]

Hello [first name], your Nevo month ends on [date]. Nothing renews on its own, so if you want to keep going, buy another month before then and your lessons carry on without a break.

Button: Buy another month

Your work and your progress stay where they are either way.

**Renewal reminder, the day it lapses**

Subject: Your Nevo month ended today

Hello [first name], your Nevo month ended today. Your work and your progress are all still here. Buy another month whenever you are ready and you pick up exactly where you left off.

Button: Buy another month

Both reminders go. Three days alone is too late, and without the second one the lapse is silent because nothing auto-renews.

---

## Lessons

**Could not be prepared**

Nevo could not prepare this one. Try uploading it again, and if it still does not work, send it to us and we will look at it.

**Refused on the hard tier**

Nevo can't teach this one. The passage on page [n] tells a reader to harm themselves and keep it from an adult, and that isn't something Nevo will teach. If you think that's wrong, send it to us and we'll look at it.

Flagged content, as distinct from a hard refusal, does not produce a message. It releases to the learner with the passage named, because they uploaded their own material off their own syllabus and there is no school on this route.

---

## Calibration

Heading: You expected [level]. You reached [level].

Matched: That is where you expected to land.

Expected more than reached: You expected to go further on this one.

Expected less than reached: You went further than you expected.

Neutral in all three directions. The mechanic exists to improve self-assessment, which it cannot do if one of the outcomes reads as a verdict.

---

## Not written, and why

**Guardian withdrawal.** No withdrawal route exists in the twenty nine endpoints, so the consent page says nothing about withdrawing. Copy follows once the path is confirmed either way.
