# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: billing.spec.ts >> @billing billing page >> @smoke every plan card names a price
- Location: tests/billing.spec.ts:9:7

# Error details

```
Error: the plan picker must name a price, not only allowances

expect(received).toMatch(expected)

Expected pattern: /[$£€]\s?\d/
Received string:  "Your WhatsApp number is disconnected, so your rep is not replying and customers are getting no answer. Reconnect it now.Open connect →
Billing·
Your plan, what it includes, and upgrades.·
Starter Plan
Active·
Renews automatically. Cancel any time and keep everything until then.·
Cancel plan
Usage·
Worst first, with what happens if one fills up.·
Team seatsin total
2 of 2·
Full. You cannot invite anyone else until you remove a member or cancel a pending invitation.·
Knowledge sourcesin total
6 of 50
Knowledge textin total
109 characters of 2,000,000 characters
Messagesthis month
0 of 1,000·
Nothing used yet. Counts what customers send and what your rep replies.·
Voice minutesthis month
0 min of 60 min·
Nothing used yet. Counts only the voice your rep speaks, rounded up to the next minute: 0 of 3,600 seconds used by this business. Voice notes your customers send are transcribed free.·
Uploaded filesin total
0 MB of 50 MB·
Nothing used yet.·
Messages and voice minutes reset on 1 Nov 2026, and on the 1st of every month after that. Seats and knowledge are running totals, so they do not reset.·
Every figure here is your business only, for the period named above.·
Compare plans to see what a larger one allows.·
How you pay·
Card details are held by our payment provider, never by us. Updating one opens their secure page.·
No card on file yet. One is saved when you first pay.·
Payment settings
Payments·
What you have been charged. Click an invoice to download it.·
No payments yet·
You are on the free trial. Anything you are charged shows up here with its invoice number.·
Change or cancel your plan above. Your rep keeps answering until the end of the period you have paid for, and payments already made are not refunded except where the law requires it.·
Billing contact·
Where invoices and payment notices go, and how to reach us about them.·
Send invoices to·
Empty, so invoices go to the address you sign in with. Set an accounts address here if that is not the right person.·
Billing questions, or a problem with a payment? billing@qonvo.org·
Plans·
Change plan any time. A change takes effect straight away, and our payment provider works out the difference for the part of the month you have already paid for. They calculate that when the change goes through rather than before it, so the exact figure appears on your next invoice below and not on this page.·
Highlighted in each plan is the allowance you are closest to using up.·
Starter·
Current plan
Messages a month
1,000
Voice minutes a month
60
Team seats
2
Knowledge sources
50·
Growth·
Upgrade
Messages a month
5,000
Voice minutes a month
180
Team seats
5
Knowledge sources
150·
Against your plan·
+4,000 messages a month
+120 voice minutes a month
+3 team seats
+100 knowledge sources·
Scale·
Upgrade
Messages a month
20,000
Voice minutes a month
480
Team seats
15
Knowledge sources
400·
Against your plan·
+19,000 messages a month
+420 voice minutes a month
+13 team seats
+350 knowledge sources"
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - generic [ref=e2]:
    - complementary [ref=e3]:
      - generic [ref=e5]:
        - img "Qonvo" [ref=e6]
        - generic [ref=e7]: qonvo
      - navigation [ref=e8]:
        - generic [ref=e9]:
          - link "Inbox" [ref=e10] [cursor=pointer]:
            - /url: /inbox
          - link "Analytics" [ref=e14] [cursor=pointer]:
            - /url: /analytics
        - generic [ref=e17]:
          - paragraph [ref=e18]: AI rep
          - link "Knowledge" [ref=e19] [cursor=pointer]:
            - /url: /knowledge
          - link "Behavior" [ref=e22] [cursor=pointer]:
            - /url: /behavior
          - link "Skills" [ref=e24] [cursor=pointer]:
            - /url: /skills
        - generic [ref=e28]:
          - paragraph [ref=e29]: Connections
          - link "WhatsApp" [ref=e30] [cursor=pointer]:
            - /url: /onboarding/connect
          - link "Integrations" [ref=e33] [cursor=pointer]:
            - /url: /integrations
        - generic [ref=e36]:
          - paragraph [ref=e37]: Workspace
          - link "Business" [ref=e38] [cursor=pointer]:
            - /url: /business
          - link "Team" [ref=e43] [cursor=pointer]:
            - /url: /team
          - link "Billing" [ref=e49] [cursor=pointer]:
            - /url: /billing
      - generic [ref=e52]:
        - button "Show me around" [ref=e54]
        - paragraph [ref=e58]: Never miss a customer.
    - generic [ref=e59]:
      - banner [ref=e60]:
        - generic [ref=e61]:
          - paragraph [ref=e62]: Dev Tenant (dev)
          - generic [ref=e63]: Owner
          - generic "This is the staging environment, not production." [ref=e64]: Staging
        - generic [ref=e65]:
          - generic [ref=e66]:
            - switch "Pause my rep" [checked] [ref=e67]
            - button "Rep on" [ref=e69]
          - button "Notifications, 25 unread" [ref=e72]:
            - generic [ref=e76]: 9+
          - button "Open account menu D" [ref=e78]:
            - generic [ref=e79]: Open account menu
            - text: D
      - main [ref=e80]:
        - link "Your WhatsApp number is disconnected, so your rep is not replying and customers are getting no answer. Reconnect it now.Open connect →" [ref=e81] [cursor=pointer]:
          - /url: /onboarding/connect
        - generic [ref=e86]:
          - generic [ref=e87]:
            - heading "Billing" [level=1] [ref=e88]
            - paragraph [ref=e89]: Your plan, what it includes, and upgrades.
          - generic [ref=e90]:
            - generic [ref=e93]:
              - heading "starter plan" [level=3] [ref=e94]
              - generic [ref=e95]: Active
            - generic [ref=e97]:
              - paragraph [ref=e98]: Renews automatically. Cancel any time and keep everything until then.
              - button "Cancel plan" [ref=e99]
          - generic [ref=e100]:
            - generic [ref=e102]:
              - heading "Usage" [level=3] [ref=e103]
              - paragraph [ref=e104]: Worst first, with what happens if one fills up.
            - generic [ref=e106]:
              - generic [ref=e107]:
                - generic [ref=e108]:
                  - generic [ref=e109]: Team seatsin total
                  - generic [ref=e110]: 2 of 2
                - progressbar "Team seats" [ref=e111]
                - paragraph [ref=e113]: Full. You cannot invite anyone else until you remove a member or cancel a pending invitation.
              - generic [ref=e114]:
                - generic [ref=e115]:
                  - generic [ref=e116]: Knowledge sourcesin total
                  - generic [ref=e117]: 6 of 50
                - progressbar "Knowledge sources" [ref=e118]
              - generic [ref=e120]:
                - generic [ref=e121]:
                  - generic [ref=e122]: Knowledge textin total
                  - generic [ref=e123]: 109 characters of 2,000,000 characters
                - progressbar "Knowledge text" [ref=e124]
              - generic [ref=e125]:
                - generic [ref=e126]:
                  - generic [ref=e127]: Messagesthis month
                  - generic [ref=e128]: 0 of 1,000
                - progressbar "Messages" [ref=e129]
                - paragraph [ref=e131]: Nothing used yet. Counts what customers send and what your rep replies.
              - generic [ref=e132]:
                - generic [ref=e133]:
                  - generic [ref=e134]: Voice minutesthis month
                  - generic [ref=e135]: 0 min of 60 min
                - progressbar "Voice minutes" [ref=e136]
                - paragraph [ref=e138]: "Nothing used yet. Counts only the voice your rep speaks, rounded up to the next minute: 0 of 3,600 seconds used by this business. Voice notes your customers send are transcribed free."
              - generic [ref=e139]:
                - generic [ref=e140]:
                  - generic [ref=e141]: Uploaded filesin total
                  - generic [ref=e142]: 0 MB of 50 MB
                - progressbar "Uploaded files" [ref=e143]
                - paragraph [ref=e145]: Nothing used yet.
              - generic [ref=e146]:
                - paragraph [ref=e147]: Messages and voice minutes reset on 1 Nov 2026, and on the 1st of every month after that. Seats and knowledge are running totals, so they do not reset.
                - paragraph [ref=e148]: Every figure here is your business only, for the period named above.
              - paragraph [ref=e149]:
                - link "Compare plans" [ref=e150] [cursor=pointer]:
                  - /url: "#plans"
                - text: to see what a larger one allows.
          - generic [ref=e151]:
            - generic [ref=e153]:
              - heading "How you pay" [level=3] [ref=e154]
              - paragraph [ref=e155]: Card details are held by our payment provider, never by us. Updating one opens their secure page.
            - generic [ref=e157]:
              - paragraph [ref=e158]: No card on file yet. One is saved when you first pay.
              - button "Payment settings" [ref=e159]
          - generic [ref=e162]:
            - generic [ref=e164]:
              - heading "Payments" [level=3] [ref=e165]
              - paragraph [ref=e166]: What you have been charged. Click an invoice to download it.
            - generic [ref=e167]:
              - generic [ref=e173]:
                - paragraph [ref=e174]: No payments yet
                - paragraph [ref=e175]: You are on the free trial. Anything you are charged shows up here with its invoice number.
              - paragraph [ref=e176]: Change or cancel your plan above. Your rep keeps answering until the end of the period you have paid for, and payments already made are not refunded except where the law requires it.
          - generic [ref=e177]:
            - generic [ref=e179]:
              - heading "Billing contact" [level=3] [ref=e180]
              - paragraph [ref=e181]: Where invoices and payment notices go, and how to reach us about them.
            - generic [ref=e182]:
              - generic [ref=e183]:
                - generic [ref=e184]: Send invoices to
                - textbox "Send invoices to" [ref=e186]:
                  - /placeholder: accounts@yourbusiness.com
                - paragraph [ref=e187]: Empty, so invoices go to the address you sign in with. Set an accounts address here if that is not the right person.
              - paragraph [ref=e188]:
                - text: Billing questions, or a problem with a payment?
                - link "billing@qonvo.org" [ref=e189] [cursor=pointer]:
                  - /url: mailto:billing@qonvo.org
          - generic [ref=e190]:
            - generic [ref=e192]:
              - heading "Plans" [level=3] [ref=e193]
              - paragraph [ref=e194]: Change plan any time. A change takes effect straight away, and our payment provider works out the difference for the part of the month you have already paid for. They calculate that when the change goes through rather than before it, so the exact figure appears on your next invoice below and not on this page.
            - generic [ref=e195]:
              - paragraph [ref=e196]: Highlighted in each plan is the allowance you are closest to using up.
              - generic [ref=e197]:
                - generic [ref=e198]:
                  - paragraph [ref=e199]: Starter
                  - button "Current plan" [disabled] [ref=e200]
                - generic [ref=e201]:
                  - generic [ref=e202]:
                    - term [ref=e203]: Messages a month
                    - definition [ref=e204]: 1,000
                  - generic [ref=e205]:
                    - term [ref=e206]: Voice minutes a month
                    - definition [ref=e207]: "60"
                  - generic [ref=e208]:
                    - term [ref=e209]: Team seats
                    - definition [ref=e210]: "2"
                  - generic [ref=e211]:
                    - term [ref=e212]: Knowledge sources
                    - definition [ref=e213]: "50"
              - generic [ref=e214]:
                - generic [ref=e215]:
                  - paragraph [ref=e216]: Growth
                  - button "Upgrade" [ref=e217]
                - generic [ref=e218]:
                  - generic [ref=e219]:
                    - term [ref=e220]: Messages a month
                    - definition [ref=e221]: 5,000
                  - generic [ref=e222]:
                    - term [ref=e223]: Voice minutes a month
                    - definition [ref=e224]: "180"
                  - generic [ref=e225]:
                    - term [ref=e226]: Team seats
                    - definition [ref=e227]: "5"
                  - generic [ref=e228]:
                    - term [ref=e229]: Knowledge sources
                    - definition [ref=e230]: "150"
                - generic [ref=e231]:
                  - paragraph [ref=e232]: Against your plan
                  - list [ref=e233]:
                    - listitem [ref=e234]: +4,000 messages a month
                    - listitem [ref=e235]: +120 voice minutes a month
                    - listitem [ref=e236]: +3 team seats
                    - listitem [ref=e237]: +100 knowledge sources
              - generic [ref=e238]:
                - generic [ref=e239]:
                  - paragraph [ref=e240]: Scale
                  - button "Upgrade" [ref=e241]
                - generic [ref=e242]:
                  - generic [ref=e243]:
                    - term [ref=e244]: Messages a month
                    - definition [ref=e245]: 20,000
                  - generic [ref=e246]:
                    - term [ref=e247]: Voice minutes a month
                    - definition [ref=e248]: "480"
                  - generic [ref=e249]:
                    - term [ref=e250]: Team seats
                    - definition [ref=e251]: "15"
                  - generic [ref=e252]:
                    - term [ref=e253]: Knowledge sources
                    - definition [ref=e254]: "400"
                - generic [ref=e255]:
                  - paragraph [ref=e256]: Against your plan
                  - list [ref=e257]:
                    - listitem [ref=e258]: +19,000 messages a month
                    - listitem [ref=e259]: +420 voice minutes a month
                    - listitem [ref=e260]: +13 team seats
                    - listitem [ref=e261]: +350 knowledge sources
  - alert [ref=e262]
```

# Test source

```ts
  1  | import { test, expect } from "@playwright/test";
  2  | import { gotoPage, failOnConsoleErrors } from "../lib/app";
  3  | 
  4  | /**
  5  |  * Billing is where money changes hands, so it carries the most regression
  6  |  * weight. Every assertion here is a bug that actually reached production.
  7  |  */
  8  | test.describe("@billing billing page", () => {
  9  |   test("@smoke every plan card names a price", async ({ page }) => {
  10 |     // Audit F2, 3 Oct 2026: /api/billing/plans carried no price field at all,
  11 |     // so the picker showed four allowances and no cost. The owner pressed
  12 |     // Choose and met the figure for the first time on the gateway's page.
  13 |     await gotoPage(page, "/billing");
  14 |     const cards = page.locator('[data-testid="plan-card"], main >> text=/^(Starter|Growth|Scale)$/');
  15 |     await expect(page.getByRole("button", { name: /Choose|Upgrade|Switch to this|Current plan/ }).first()).toBeVisible();
  16 | 
  17 |     const main = await page.locator("main").innerText();
> 18 |     expect(main, "the plan picker must name a price, not only allowances").toMatch(/[$£€]\s?\d/);
     |                                                                            ^ Error: the plan picker must name a price, not only allowances
  19 |   });
  20 | 
  21 |   test("the plan picker offers every paid plan", async ({ page }) => {
  22 |     await gotoPage(page, "/billing");
  23 |     const main = await page.locator("main").innerText();
  24 |     for (const plan of ["Starter", "Growth", "Scale"]) {
  25 |       expect(main, `${plan} must be offered`).toContain(plan);
  26 |     }
  27 |     expect(main, "the trial is not something you can buy").not.toMatch(/\bChoose\b[\s\S]{0,40}\bTrial\b/);
  28 |   });
  29 | 
  30 |   test("the trial banner does not send the owner to a human", async ({ page }) => {
  31 |     // Audit F4: the banner said "Contact your Qonvo rep to go paid" while
  32 |     // self-serve checkout worked three clicks away.
  33 |     await gotoPage(page, "/billing");
  34 |     const body = await page.locator("body").innerText();
  35 |     expect(body).not.toContain("Contact your Qonvo rep to go paid");
  36 |   });
  37 | 
  38 |   test("our cost of goods never reaches the tenant", async ({ page }) => {
  39 |     // Audit, 12 Sep: `cost` stayed in the analytics payload after the tile was
  40 |     // removed, so a customer with the network tab open could read our margin.
  41 |     const leaked: string[] = [];
  42 |     page.on("response", async (res) => {
  43 |       if (!res.url().includes("/api/analytics")) return;
  44 |       try {
  45 |         const body = await res.text();
  46 |         if (/"cost"\s*:/.test(body)) leaked.push(res.url());
  47 |       } catch {
  48 |         /* streamed */
  49 |       }
  50 |     });
  51 |     await gotoPage(page, "/analytics");
  52 |     await page.waitForTimeout(2000);
  53 |     expect(leaked, "analytics must not ship our cost of goods").toEqual([]);
  54 |   });
  55 | 
  56 |   test("a billing call that fails does not answer 200", async ({ page, request }) => {
  57 |     // Audit L3 (11 Sep) and F3 (3 Oct): change-plan, cancel and resume all
  58 |     // returned 200 {"ok": false}, so a client reading the status code believed
  59 |     // the plan had changed.
  60 |     const apiBase = (process.env.QONVO_E2E_API ?? "https://dev-api.qonvo.org").replace(/\/$/, "");
  61 |     const login = await request.post(`${apiBase}/api/auth/login`, {
  62 |       data: {
  63 |         email: process.env.QONVO_E2E_OWNER_EMAIL ?? "owner@dev.dev",
  64 |         password: process.env.QONVO_E2E_OWNER_PASSWORD ?? "dev-password-123",
  65 |       },
  66 |     });
  67 |     test.skip(!login.ok(), "no API login on this environment");
  68 |     const token = (await login.json()).access_token;
  69 | 
  70 |     const res = await request.post(`${apiBase}/api/billing/change-plan`, {
  71 |       headers: { Authorization: `Bearer ${token}` },
  72 |       data: { plan_key: "growth" },
  73 |       failOnStatusCode: false,
  74 |     });
  75 |     const body = await res.json().catch(() => ({}));
  76 |     if (body?.ok === false) {
  77 |       expect(res.status(), "a refusal must carry a failure status").not.toBe(200);
  78 |     }
  79 |   });
  80 | 
  81 |   test("the billing page renders without console errors", async ({ page }) => {
  82 |     const errors: string[] = [];
  83 |     failOnConsoleErrors(page, errors);
  84 |     await gotoPage(page, "/billing");
  85 |     await page.waitForTimeout(1500);
  86 |     expect(errors).toEqual([]);
  87 |   });
  88 | });
  89 | 
```