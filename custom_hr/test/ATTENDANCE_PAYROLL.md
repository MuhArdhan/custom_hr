# Automatic attendance payroll

Only custom_hr changes payroll; native HRMS source remains untouched.
Two DocTypes configure company/date policies and child category rules.

## Setup

1. Payroll → Setup → Aturan Presensi Payroll: choose company and effective dates.
2. Set category, Salary Component (Deduction), unit, method and values.
3. Enable **Terapkan Potongan Otomatis** for categories to apply to payroll.
   Disabled rules remain count-only. Existing settings are not automatically enabled.
4. Add exactly one matching component to Salary Structure deductions with amount 0,
   no formula/condition, no Depends on Payment Days, and no statistical/tax/accrual
   or exclude-from-total flags. Accounting flags are preserved unchanged.
   Other earning/deduction formulas remain native.

Alpha example: method Base / Pembagi, unit Hari, divisor 22, multiplier 0.75.
Base is taken from the employee/company's submitted SSA effective on each date.
Rp4,400,000 × 0.75 / 22 × 1 day = Rp150,000.
Hours use measured lateness / 60 or explicit HR day conversion for Alpha/Izin.

## Runtime

Salary Slip calculation loads the native structure, computes attendance amounts,
and updates managed structure rows before native totals/YTD calculation. Repeated
calculation updates the same row; it never creates Additional Salary. JSON stores
source rules, SSA Base, quantities, calculated amounts and verification warnings.
Drafts can show partial estimates for a period that is not yet complete; snapshot
warnings identify gaps. Submit rejects incomplete data and inconsistent amounts.
Submitted slips do not refresh attendance from live data.

Additional Salary for a managed component (including recurring records), duplicate
components, conflicting formulas/flags and native LWP/payment-day double charges
are blocked. Native LWP remains authoritative; disable the automatic Izin rule.
Alpha when payroll is based on Attendance is likewise blocked if already handled
by native payment days. No global Payroll Settings are changed automatically.

Deploy custom_hr changes, migrate, restart Python processes, and hard-refresh Desk.
Tests: `env/bin/python -m unittest discover -s apps/custom_hr/custom_hr/test -p 'test_*.py'`.
