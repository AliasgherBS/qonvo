# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: billing.spec.ts >> @billing billing page >> our cost of goods never reaches the tenant
- Location: tests/billing.spec.ts:38:7

# Error details

```
Error: analytics must not ship our cost of goods

expect(received).toEqual(expected) // deep equality

- Expected  - 1
+ Received  + 3

- Array []
+ Array [
+   "https://dev-api.qonvo.org/api/analytics/summary?days=30",
+ ]
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
            - generic [ref=e88]:
              - heading "Analytics" [level=1] [ref=e89]
              - paragraph [ref=e90]: What your rep did over the last 30 days, against the 30 before it.
            - group "Date range" [ref=e91]:
              - button "7 days" [ref=e92]
              - button "30 days" [pressed] [ref=e93]
              - button "90 days" [ref=e94]
          - generic [ref=e95]:
            - generic [ref=e96]:
              - generic [ref=e98]:
                - paragraph [ref=e99]: Messages answered
                - paragraph [ref=e100]: "125"
                - paragraph [ref=e101]:
                  - generic [ref=e102]: up from none
                  - generic [ref=e106]: vs the previous 30 days (0)
                - paragraph [ref=e107]: Replies sent from your number, by the rep and by your team.
              - generic [ref=e109]:
                - paragraph [ref=e110]: Bookings and leads
                - paragraph [ref=e111]: "0"
                - paragraph [ref=e112]: Nothing in the previous 30 days to compare with.
                - paragraph [ref=e113]: 0 bookings · 0 leads · 0 orders
            - generic [ref=e114]:
              - generic [ref=e115]:
                - paragraph [ref=e116]: Messages received
                - paragraph [ref=e117]: "191"
              - generic [ref=e118]:
                - paragraph [ref=e119]: Conversations
                - paragraph [ref=e120]: "22"
              - generic [ref=e121]:
                - paragraph [ref=e122]: Needs human now
                - paragraph [ref=e123]: "6"
              - generic [ref=e124]:
                - paragraph [ref=e125]: Open handoffs
                - paragraph [ref=e126]: "6"
            - generic [ref=e128]:
              - generic [ref=e129]:
                - paragraph [ref=e130]: Day by day
                - group "Activity view" [ref=e131]:
                  - button "Messages" [pressed] [ref=e132]
                  - button "Voice" [ref=e133]
              - generic [ref=e134]:
                - generic [ref=e135]:
                  - paragraph [ref=e136]: Received
                  - paragraph [ref=e137]: "191"
                - generic [ref=e138]:
                  - paragraph [ref=e139]: Replies sent
                  - paragraph [ref=e140]: "125"
                - generic [ref=e141]:
                  - paragraph [ref=e142]: Average question
                  - paragraph [ref=e143]: 18 chars
                - generic [ref=e144]:
                  - paragraph [ref=e145]: Average reply
                  - paragraph [ref=e146]: 136 chars
              - generic [ref=e147]:
                - generic [ref=e149]:
                  - generic [ref=e150]: "106"
                  - generic [ref=e151]: "53"
                  - generic [ref=e152]: "0"
                - generic [ref=e153]:
                  - generic [ref=e155]:
                    - 'button "Sat, Sep 5: 25 Replies sent, 27 Received" [ref=e156]'
                    - 'button "Sun, Sep 6: 51 Replies sent, 55 Received" [ref=e160]'
                    - 'button "Mon, Sep 7: 17 Replies sent, 18 Received" [ref=e164]'
                    - 'button "Tue, Sep 8: 29 Replies sent, 31 Received" [ref=e168]'
                    - 'button "Wed, Sep 9: 0 Replies sent, 0 Received" [ref=e172]'
                    - 'button "Thu, Sep 10: 3 Replies sent, 60 Received" [ref=e173]'
                  - generic [ref=e177]:
                    - generic [ref=e178]: Sep 5
                    - generic [ref=e179]: Sep 6
                    - generic [ref=e180]: Sep 7
                    - generic [ref=e181]: Sep 8
                    - generic [ref=e182]: Sep 9
                    - generic [ref=e183]: Sep 10
                  - generic [ref=e184]:
                    - generic [ref=e185]: Replies sent
                    - generic [ref=e187]: Received
            - generic [ref=e190]:
              - generic [ref=e191]:
                - paragraph [ref=e192]: Top questions the bot couldn't answer
                - link "Answer these in Knowledge" [ref=e193] [cursor=pointer]:
                  - /url: /knowledge
              - list [ref=e194]:
                - listitem [ref=e195]:
                  - generic [ref=e196]: do you do keratin treatment?
                  - generic [ref=e197]: ×1
                - listitem [ref=e198]:
                  - generic [ref=e199]: kitne ka hai haircut?
                  - generic [ref=e200]: ×1
                - listitem [ref=e201]:
                  - generic [ref=e202]: how much for a facial?
                  - generic [ref=e203]: ×1
                - listitem [ref=e204]:
                  - generic [ref=e205]: what services do you offer for men?
                  - generic [ref=e206]: ×1
                - listitem [ref=e207]:
                  - generic [ref=e208]: do you have parking?
                  - generic [ref=e209]: ×1
  - alert [ref=e210]
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
  18 |     expect(main, "the plan picker must name a price, not only allowances").toMatch(/[$£€]\s?\d/);
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
> 53 |     expect(leaked, "analytics must not ship our cost of goods").toEqual([]);
     |                                                                 ^ Error: analytics must not ship our cost of goods
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