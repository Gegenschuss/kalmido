# Household budget

*Since 2.72.0.* A simple budget for your household, part of the area **Home**: what comes in, what goes out and what is
left at the end of the month. Switch it on under *Settings > Modules > Home > Budget* (off by default).

## Getting started

- On *Home & life* the card **Budget** offers *Create a budget*. A budget is a list of its own with a few default
  categories (housing, groceries, transport, insurance, leisure, other; salary, other income).
- Share it with your family like any list (menu **…** > *Share*): people with read access see everything but cannot
  change anything; people allowed to edit can add and change entries.
- Budgets are private: they are never visible to agents and cannot be shared with an agent.

## The month

- **‹ Month ›** switches the month; *This month* leads back.
- On top: *Received*, *Spent* (each with what is planned) and *Left over* (received minus spent), below the last six
  months as small bars.
- **Categories** show what was spent against the plan. The plan of a category is its *monthly limit*; without a limit
  it is the sum of the recurring entries of that category. Over the limit, the bar turns red.
- **Open this month** lists the recurring entries due in this month. They are never booked on their own: tap *Booked*
  when the money has actually gone (or come in).
- **+ Entry** adds an expense or an income: amount (comma or point), date, what it was, category, paid to / from and a
  note. Open an entry again to add receipts (pictures, PDFs) or to delete it. Every change can be undone.
- **Month comparison** (2.140, below the bars): one card per category with what was spent (or received) in the shown
  month, its plan, the difference to the month before and to the average of the earlier months (in money and percent;
  more spending is marked red, less in the accent colour) and a small bar per month. Choose 3, 6 or 12 months.

## Recurring entries and contracts

- Menu **…** > *Recurring entries*: rent, salary, insurance with how often (monthly, quarterly, yearly), from which
  month and, if it ends, until which month.
- With the module *Contracts* on, *Take over from contracts* turns your contracts with a cost into recurring entries.
  The values are copied; if a contract changes later, the budget says *Contract changed* and *Match it* takes the new
  cost over.

## Importing your bank statement (CSV or CAMT)

Kalmido has **no access to your bank**. Download the CSV export (or the CAMT.052 / .053 XML file) of your account
statement from your bank yourself and choose it under menu **…** > *Import a CSV file*. Since 2.140 the budget reads the
file with the same reader as the bank import of the office (same formats and checks; nothing is shared between the two):

0. A CAMT file goes straight to the preview (day, amount in or out, purpose, counterpart); a booking in another currency
   than the rest of the file is not taken. Some bank layouts are recognised by their columns and pre-filled ("Recognised
   layout"); you still check them like the guess.

1. Kalmido guesses which column holds the date, the amount (one column with minus for expenses, or income and expense
   apart), the text and who was paid; check the guess, the decimal separator and the date format.
2. The preview lists every row. Rows that are already in the budget are marked and not chosen; a row that matches an
   open recurring entry is linked to it (so it is not counted twice). The category can be changed per row.
3. *Take over N entries* imports the chosen rows. The column mapping is remembered for the next file of the same bank.

Amounts, titles, notes and receipts are stored encrypted on the server.
