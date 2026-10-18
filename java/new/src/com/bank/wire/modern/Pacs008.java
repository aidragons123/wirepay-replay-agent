package com.bank.wire.modern;

/** NEW OUTPUT MODEL: ISO 20022 pacs.008.001.08 (FIToFICustomerCreditTransfer), one transaction. */
public final class Pacs008 {
    private Pacs008() {
    }

    public record Data(String paymentId, String uetr, String processingDate, String amount, String currency,
                       String settlementDate, String chargeBearer, String fee, String instructingBic,
                       String debtorName, String debtorAccount, String creditorBic, String creditorName,
                       String creditorAccount, String remittance) {
    }

    public static String build(Data d) {
        return """
                <?xml version="1.0" encoding="UTF-8"?>
                <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08">
                <FIToFICstmrCdtTrf>
                <GrpHdr><MsgId>%s</MsgId><CreDtTm>%sT00:00:00</CreDtTm><NbOfTxs>1</NbOfTxs><SttlmInf><SttlmMtd>INDA</SttlmMtd></SttlmInf></GrpHdr>
                <CdtTrfTxInf>
                <PmtId><InstrId>%s</InstrId><EndToEndId>%s</EndToEndId><UETR>%s</UETR></PmtId>
                <IntrBkSttlmAmt Ccy="%s">%s</IntrBkSttlmAmt>
                <IntrBkSttlmDt>%s</IntrBkSttlmDt>
                <ChrgBr>%s</ChrgBr>
                <ChrgsInf><Amt Ccy="%s">%s</Amt><Agt><FinInstnId><BICFI>%s</BICFI></FinInstnId></Agt></ChrgsInf>
                <Dbtr><Nm>%s</Nm></Dbtr>
                <DbtrAcct><Id>%s</Id></DbtrAcct>
                <DbtrAgt><FinInstnId><BICFI>%s</BICFI></FinInstnId></DbtrAgt>
                <CdtrAgt><FinInstnId><BICFI>%s</BICFI></FinInstnId></CdtrAgt>
                <Cdtr><Nm>%s</Nm></Cdtr>
                <CdtrAcct><Id>%s</Id></CdtrAcct>
                <RmtInf><Ustrd>%s</Ustrd></RmtInf>
                </CdtTrfTxInf>
                </FIToFICstmrCdtTrf>
                </Document>
                """.formatted(
                x(d.paymentId()), x(d.processingDate()),
                x(d.paymentId()), x(d.paymentId()), x(d.uetr()),
                x(d.currency()), x(d.amount()),
                x(d.settlementDate()),
                x(d.chargeBearer()),
                x(d.currency()), x(d.fee()), x(d.instructingBic()),
                x(d.debtorName()),
                account(d.debtorAccount()),
                x(d.instructingBic()),
                x(d.creditorBic()),
                x(d.creditorName()),
                account(d.creditorAccount()),
                x(d.remittance()));
    }

    private static String account(String a) {
        return Iban.looksLikeIban(a)
                ? "<IBAN>" + x(a) + "</IBAN>"
                : "<Othr><Id>" + x(a) + "</Id></Othr>";
    }

    static String x(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\"", "&quot;").replace("'", "&apos;");
    }
}
