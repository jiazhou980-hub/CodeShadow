sql练习
loan_apply(apply_id, customer_id, apply_date, product_type, apply_amount, approve_status)
loan_contract(contract_id, apply_id, customer_id, sign_date, loan_amount, term_months, interest_rate)
repay_plan(contract_id, period_no, due_date, due_principal, due_interest)
repay_detail(contract_id, repay_date, repay_principal, repay_interest)
customer(customer_id, gender, age, city, risk_level)

题 1：月度放款统计
统计每个月、每个信贷产品的：
放款合同数
放款金额
平均放款金额
最大放款金额
只统计已签约合同。
select date_format(lc.sign_date,'yyyy-MM')
        ,la.product_type
        ,count(*) as customer_cnt
        ,sum(lc.loan_amount) as total_loan_customer
        ,avg(lc.loan_amount) as avg_loan_customer
        ,max(lc.loan_amount) as max_loan_customer
from loan_apply la join loan_contract lc on la.apply_id=lc.apply_id
group by date_format(lc.sign_date,'yyyy-MM'),la.product_type;

题 2：客户首贷识别
找出每个客户的第一笔贷款合同，输出：
customer_id
contract_id
sign_date
loan_amount
如果同一天有多笔合同，取 loan_amount 最大的一笔。
