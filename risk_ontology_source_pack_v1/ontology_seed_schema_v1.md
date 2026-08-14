# 企业信用与授信风险 Ontology 候选模式 V1

## 1. 范围

首版建议限定为“企业信用风险、银行授信风险及风险处置”，不覆盖市场风险、操作风险等全部风险管理领域。

## 2. 顶层对象类型

### 主体
- Organization
  - Company
  - ListedCompany
  - Bank
  - BankBranch
  - Court
  - Regulator
  - AuditFirm
  - Administrator
  - InvestorProtectionInstitution
- Person
  - Controller
  - Director
  - BankEmployee
  - Accountant
  - Investor

### 金融与法律对象
- FinancialInstrument
  - Loan
  - Bond
  - Guarantee
  - SecuredClaim
- Claim
- Contract
- AnnualReport
- Prospectus
- AuditReport
- PenaltyDecision
- CourtRuling
- RestructuringPlan

### 事件
- BusinessEvent
  - FinancingEvent
  - FundTransfer
  - RelatedTransaction
  - AssetDisposition
- RiskEvent
  - LoanMisappropriation
  - FalseStatement
  - FraudulentIPO
  - DebtOverdue
  - BondDefault
  - CashChainBreak
  - AssetSeizure
- ResolutionEvent
  - DebtRestructuring
  - PreRestructuring
  - BankruptcyRestructuring
  - Delisting
  - InvestorCompensation

### 治理与控制
- ControlProcedure
  - PreLoanInvestigation
  - CreditReview
  - PostLoanInspection
  - UnifiedCreditManagement
  - RiskClassification
- Violation
- Penalty

## 3. 关键关系

- `controls(Person|Organization, Organization)`
- `is_related_to(Organization, Organization)`
- `guarantees_for(Organization, Organization|FinancialInstrument)`
- `grants_loan(Bank|BankBranch, Company)`
- `uses_funds_for(Company, Purpose)`
- `funds_flow_to(FundTransfer, Organization)`
- `discloses(Document, Fact|Event)`
- `contradicted_by(Document, PenaltyDecision|CourtRuling)`
- `audits(AuditFirm, AnnualReport)`
- `issues_penalty(Regulator, Organization|Person)`
- `files_claim(Creditor, Claim)`
- `applies_for(Creditor, RestructuringProceeding)`
- `accepts(Court, Proceeding)`
- `appoints(Court, Administrator)`
- `restructures(RestructuringPlan, FinancialDebt)`
- `compensates(Organization|Fund, Investor)`
- `supported_by(Fact|Rule, EvidenceSource)`

## 4. 必须保留的证据与时间属性

所有实例事实必须带：

- `source_id`
- `source_url`
- `source_date`
- `source_type`
- `source_excerpt` 或页码/段落
- `event_time`
- `knowledge_time`
- `knowledge_status`
- `confidence`
- `review_status`

## 5. 类与实例边界

- “华夏幸福”是 Company 实例，不是类。
- “债务逾期”是 RiskEvent 类型；具体的某次逾期是实例。
- “关联方识别不全面”可建为 Violation 类型；某家银行的处罚事实是实例。
- “实质合并重整”是 Proceeding/Resolution 类型；江苏纺织集团案是实例。

## 6. 第一批可回答的问题

1. 某企业风险暴露前有哪些已知的融资、担保和现金流异常？
2. 某处罚案例涉及授信流程的哪个环节？
3. 哪些案例同时出现关联方识别失败和贷款资金挪用？
4. 某公司从债务逾期到预重整经历了哪些事件？
5. 某风险事实由哪些年度报告、处罚决定和法院材料支持？
