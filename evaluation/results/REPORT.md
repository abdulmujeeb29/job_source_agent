# Evaluation results

Verified success rate: **11/20 (55%)**.

- Agent outcomes: `{'succeeded': 11, 'failed': 9}`
- Distinct extracted companies: 18
- Model requests: 105; input + output tokens: 1,161,091.
- Median run time: 53.5s; maximum: 152.0s.

| # | Input | Company | Agent status | Jobs URL | Seconds | Reviewed success | Notes |
|---|---|---|---|---|---|---|---|
| 1 | https://www.linkedin.com/jobs/view/4464950014/ | U.S. Bank | succeeded | https://careers.usbank.com/global/en/search-results | 66.0 | yes | Reviewed U.S. Bank branded search screenshot, 1400 results, observed role links and successful sampled detail check. |
| 2 | https://www.linkedin.com/jobs/view/4410261275/ | Plaid | failed | None | 125.7 | no | Failed verification because generic See role anchors did not contain role titles. Jobs collection was found, but no successful final result returned. |
| 3 | https://www.linkedin.com/jobs/view/4465237802/ | Intelligent People | failed | None | 152.0 | no | Company-name excerpt could not be grounded on the recruitment board. Agent returned explicit failure. |
| 4 | https://www.linkedin.com/jobs/view/4459955796/ | Redcare Pharmacy | succeeded | https://www.redcare-pharmacy.com/careers/open-jobs | 38.4 | yes | Reviewed Redcare Pharmacy screenshot showing 226 jobs and Digital Analytics Manager; grounded links and sampled HTTP 200 detail check. |
| 5 | https://www.linkedin.com/jobs/view/4445180104/ | Movate | failed | None | 86.1 | no | Navigation cycle guard stopped repeated actions without progress. No jobs URL returned. |
| 6 | https://www.linkedin.com/jobs/view/4464873466/ | Corpay | succeeded | https://corpay.wd103.myworkdayjobs.com/Ext_001 | 71.6 | yes | Reviewed Corpay branded Workday board screenshot, 104 jobs, Client Support and Regulatory Compliance Manager; sampled detail HTTP 200. |
| 7 | https://www.linkedin.com/jobs/view/4438098210/ | Plum | failed | None | 87.6 | no | Navigation cycle guard stopped repeated actions without progress. No jobs URL returned. |
| 8 | https://www.linkedin.com/jobs/view/4459681392/ | DISH Digital Solutions | succeeded | https://dishdigital.jobs.personio.de/ | 50.4 | yes | Reviewed DISH branded Personio board, German Offene Stellen heading and visible Senior Data Analyst/Engineer roles; sampled detail HTTP 200. |
| 9 | https://www.linkedin.com/jobs/view/4461910203/ | Western Financial Group | failed | None | 37.3 | no | Company website navigation failed with ERR_HTTP_RESPONSE_CODE_FAILURE; no verified result returned. |
| 10 | https://www.linkedin.com/jobs/view/4455913300/ | None | failed | None | 18.5 | no | Company enrichment returned no official website; extraction failure retained in denominator. |
| 11 | https://www.linkedin.com/jobs/view/4467433945/ | Quik Hire Staffing | failed | None | 42.0 | no | Company website navigation failed with ERR_TUNNEL_CONNECTION_FAILED; no verified result returned. |
| 12 | https://www.linkedin.com/jobs/view/4463903973/ | USAA | succeeded | https://www.usaajobs.com/search-jobs/ | 51.7 | yes | Reviewed USAA-branded search page and visible list behind consent dialog; 210 jobs, observed role links and sampled HTTP 200 detail check. |
| 13 | https://www.linkedin.com/jobs/view/4461020080/ | Bolt.Earth | failed | None | 104.2 | no | Cycle guard stopped repeated actions without progress; no final jobs URL. |
| 14 | https://www.linkedin.com/jobs/view/4463498563/ | Kpler | succeeded | https://jobs.lever.co/kpler | 58.5 | yes | Reviewed Kpler-branded Lever board screenshot, multiple visible analyst roles and matching observed links; sampled detail HTTP 200. |
| 15 | https://www.linkedin.com/jobs/view/4464117270/ | Affirm | succeeded | https://www.affirm.com/careers | 43.4 | yes | Independent browser check after dismissing region modal confirmed Analytics Engineer II and many other roles on Affirm careers; observed Greenhouse links and sampled detail HTTP 200. |
| 16 | https://www.linkedin.com/jobs/view/4466364866/ | Worldpay | succeeded | https://jobs.globalpayments.com/jobs | 55.4 | yes | Worldpay official Careers link led directly to Global Payments careers. Reviewed this navigation chain and branded jobs screenshot with 803 roles; sampled detail HTTP 200. Parent-company shared board accepted as official destination. |
| 17 | https://www.linkedin.com/jobs/view/4463254080/ | Cint | succeeded | https://careers.smartrecruiters.com/Cint | 33.6 | yes | Independent browser check confirmed Careers at Cint and Jobs at Cint with Staff Software Engineer and multiple other roles; official SmartRecruiters destination and sampled detail HTTP 200. |
| 18 | https://www.linkedin.com/jobs/view/4464261610/ | Cloudflare | succeeded | https://www.cloudflare.com/careers/jobs/ | 47.0 | yes | Reviewed Cloudflare-branded page screenshot with 360 open roles and visible engineering listings; observed Greenhouse links and sampled detail HTTP 200. |
| 19 | https://www.linkedin.com/jobs/view/4462819834/ | Flix | succeeded | https://flix.careers/jobs/ | 71.2 | yes | Reviewed Flix-branded jobs screenshot and independently inspected the live role list; Spanish role titles and observed links match, sampled detail HTTP 200. |
| 20 | https://www.linkedin.com/jobs/view/4455936436/ | None | failed | None | 16.0 | no | Company enrichment had no official website. Failure retained in denominator. |
