# Mock data

Everything here is synthetic. The company (Fernhill Technologies), every person, and every figure were invented for a course project. Email addresses use the reserved `.example` domain.

| File | Contents |
|---|---|
| `employees.json` | 23 employee profiles: role, classification, manager, office, work arrangement, start date, data access level |
| `pto_balances.json` | PTO balances and international remote working days used this year |
| `benefits_elections.json` | Health, retirement, wellness and learning budget status |
| `offices.json` | The three offices and their holiday calendars |
| `tickets.json` | A few existing HR tickets |

## The fixed clock

The data describes one moment in time: **Monday, February 1, 2027** (`as_of_date`). The system treats that date as "today". Without a fixed date, answers such as "is this person still on probation?" would change from one day to the next, and the evaluation results could not be reproduced.

## People who test the agent

These profiles exist so that the right answer depends on the data, not only on the policy text.

| Employee | Why they are here | Policy the agent must apply |
|---|---|---|
| E1007 Dana Okafor | The ordinary case: full-time, hybrid, healthy PTO balance | POL-002, POL-005 |
| E1012 Leo Marchetti | Contractor: no PTO, no benefits, no Work From Anywhere | POL-001 section 3.4 |
| E1015 Sam Whitlock | Started January 11, 2027: on probation, cannot take PTO yet, health election pending | POL-002 section 5, POL-009 section 3 |
| E1009 Noor Haddad | Restricted data access and Finance: cannot work abroad, PTO blackout periods | POL-005 section 6, POL-002 section 6 |
| E1010 Jamie Castellano | Negative PTO balance | POL-002 section 4.2 |
| E1017 Elliot Brandvold | No assigned manager, low PTO balance, Finance | POL-002 sections 3.5 and 4.2 |
| E1014 Robin Achterberg | Part-time, 24 hours per week: prorated PTO and benefits | POL-002 section 2.3, POL-009 section 3.3 |
| E1016 Mei-Lin Zhao | Intern: no PTO, no health plan | POL-001 section 3.3 |
| E1011 Ines Carvalho | Employed in Portugal: different PTO minimum and holidays | POL-002 section 2.4, POL-003 section 5 |
| E1008 Liam Tremblay | Has already used 12 of 20 international working days | POL-005 section 5.1 |
| E1019 Kofi Mensah-Boyd | Office-based with Restricted access | POL-005 section 3 |
| E1020 Priya Nandakumar | Past probation but under 6 months: no learning budget yet | POL-009 section 7.1 |
| E1021 Wes Hargrove | On a performance improvement plan | POL-005 section 3 |
| E1018 Hannah Petrov | Currently on leave | POL-010 |
| E1022 Amara Lindgren | Reaches 5 years of service on February 14, 2027: service award and service leave | POL-023 sections 4.1 and 5.1 |
