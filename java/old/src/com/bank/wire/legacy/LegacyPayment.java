package com.bank.wire.legacy;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * The OLD payment model: one flat, mutable bean. No workflow, no audit
 * trail - the status is just a string that the service overwrites.
 */
public class LegacyPayment {
    private String paymentId;
    private String status;
    private String errorCode = "";
    private String errorMessage = "";
    private String debtorName = "";
    private String debtorAccount = "";
    private String creditorName = "";
    private String creditorAccount = "";
    private String creditorBic = "";
    private BigDecimal amount;
    private String currency = "";
    private BigDecimal fee;
    private LocalDate settlementDate;
    private String chargeBearer = "";
    private String remittanceInfo = "";

    public String getPaymentId() { return paymentId; }
    public void setPaymentId(String v) { this.paymentId = v; }
    public String getStatus() { return status; }
    public void setStatus(String v) { this.status = v; }
    public String getErrorCode() { return errorCode; }
    public void setErrorCode(String v) { this.errorCode = v; }
    public String getErrorMessage() { return errorMessage; }
    public void setErrorMessage(String v) { this.errorMessage = v; }
    public String getDebtorName() { return debtorName; }
    public void setDebtorName(String v) { this.debtorName = v; }
    public String getDebtorAccount() { return debtorAccount; }
    public void setDebtorAccount(String v) { this.debtorAccount = v; }
    public String getCreditorName() { return creditorName; }
    public void setCreditorName(String v) { this.creditorName = v; }
    public String getCreditorAccount() { return creditorAccount; }
    public void setCreditorAccount(String v) { this.creditorAccount = v; }
    public String getCreditorBic() { return creditorBic; }
    public void setCreditorBic(String v) { this.creditorBic = v; }
    public BigDecimal getAmount() { return amount; }
    public void setAmount(BigDecimal v) { this.amount = v; }
    public String getCurrency() { return currency; }
    public void setCurrency(String v) { this.currency = v; }
    public BigDecimal getFee() { return fee; }
    public void setFee(BigDecimal v) { this.fee = v; }
    public LocalDate getSettlementDate() { return settlementDate; }
    public void setSettlementDate(LocalDate v) { this.settlementDate = v; }
    public String getChargeBearer() { return chargeBearer; }
    public void setChargeBearer(String v) { this.chargeBearer = v; }
    public String getRemittanceInfo() { return remittanceInfo; }
    public void setRemittanceInfo(String v) { this.remittanceInfo = v; }
}
