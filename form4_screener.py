import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict
import csv  # For CSV export

class Form4Screener:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Form4ScreenerApp aarya.patel.email@gmail.com'
        })
        self.sec_base_url = "https://www.sec.gov"

    def get_company_filings_json(self, cik: str) -> Dict:
        """Fetch the company's submissions JSON from SEC."""
        cik = cik.zfill(10)
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json()

    def filter_form4_filings(self, filings_json: Dict, start_date: str, end_date: str) -> List[Dict]:
        """Filter Form 4 filings by date."""
        form4_filings = []
        recent = filings_json.get('filings', {}).get('recent', {})
        for form_type, fdate, acc, primary_doc in zip(
            recent.get('form', []),
            recent.get('filingDate', []),
            recent.get('accessionNumber', []),
            recent.get('primaryDocument', [])
        ):
            if form_type not in ['4', '4/A']:
                continue
            filing_dt = datetime.strptime(fdate, '%Y-%m-%d')
            if not (datetime.strptime(start_date, '%Y-%m-%d') <= filing_dt <= datetime.strptime(end_date, '%Y-%m-%d')):
                continue
            form4_filings.append({
                'accession_number': acc,
                'primaryDocument': primary_doc
            })
        return form4_filings

    def fetch_xml(self, cik: str, accession_number: str, primary_document: str) -> str:
        """Fetch Form 4 XML using primaryDocument, forcing raw XML URL."""
        cik_num = str(int(cik))
        acc_clean = accession_number.replace('-', '')
        doc_name = primary_document.split('/')[-1]
        url = f"{self.sec_base_url}/Archives/edgar/data/{cik_num}/{acc_clean}/{doc_name}"
        resp = self.session.get(url)
        resp.raise_for_status()
        if "<html" in resp.text.lower():
            raise ValueError(f"HTML page found instead of XML: {url}")
        return resp.text

    def parse_non_derivative(self, xml_content: str) -> List[Dict]:
        """Parse non-derivative transactions and classify as Buy/Sell/Other."""
        transactions = []
        root = ET.fromstring(xml_content.strip())
        ns_url = root.tag[root.tag.find("{")+1:root.tag.find("}")] if "}" in root.tag else ""
        NS = {'ns': ns_url} if ns_url else {}
        prefix = 'ns:' if ns_url else ''

        def find_text(el, path):
            if el is None:
                return None
            return el.findtext('/'.join(f"{prefix}{p}" for p in path.split('/')), None, NS)

        # Owners
        owners = []
        for owner in root.findall(f'.//{prefix}reportingOwner', NS):
            oid = owner.find(f'{prefix}reportingOwnerId', NS)
            owners.append({
                'officer_name': find_text(oid, 'rptOwnerName') or find_text(oid, 'ownerName') or 'Unknown',
                'officer_title': find_text(owner.find(f'{prefix}reportingOwnerRelationship', NS), 'officerTitle') or ''
            })

        # Non-derivative transactions
        for tx in root.findall(f'.//{prefix}nonDerivativeTransaction', NS):
            tx_code = find_text(tx, 'transactionCoding/transactionCode')
            if not tx_code:
                tx_code = find_text(tx, 'transactionCoding/transactionCode/value')
            tx_date = find_text(tx, 'transactionDate/value')
            shares = find_text(tx, 'transactionAmounts/transactionShares/value')
            price = find_text(tx, 'transactionAmounts/transactionPricePerShare/value')
            security = find_text(tx, 'securityTitle/value')

            # ✅ Classify transaction
            if tx_code and tx_code.strip() in ['P', 'F', 'A', 'M', 'E', 'J']:    # Purchase, Award, Exercise, etc.
                tx_type = 'BUY'
            elif tx_code and tx_code.strip() in ['S', 'D', 'G', 'W']:  # Sale, Disposition, Gift, Withdrawal
                tx_type = 'SELL'
            else:
                tx_type = 'OTHER'

            for owner in owners:
                transaction = {
                    **owner,
                    'transaction_code': tx_code,
                    'transaction_type': tx_type,
                    'transaction_date': tx_date,
                    'shares': shares,
                    'price_per_share': price,
                    'security_title': security
                }
                transactions.append(transaction)

                # ✅ Print each transaction immediately with transaction type
                print(f"{transaction['transaction_date']}: {transaction['officer_name']} [{tx_type}] {shares} shares of {security} at ${price}")

        return transactions


# --- Execution ---
if __name__ == "__main__":
    screener = Form4Screener()
    cik = "0000019617"  #JPM
    start_date = "2020-01-01"
    end_date = "2025-10-01"

    filings_json = screener.get_company_filings_json(cik)
    form4_filings = screener.filter_form4_filings(filings_json, start_date, end_date)

    all_transactions = []
    for f in form4_filings:
        try:
            xml = screener.fetch_xml(cik, f['accession_number'], f['primaryDocument'])
            all_transactions.extend(screener.parse_non_derivative(xml))
        except Exception as e:
            print(f"⚠️ Skipped {f['accession_number']} due to error: {e}")

    print(f"\n✅ Found {len(all_transactions)} non-derivative transactions for JPM between {start_date} and {end_date}")

    # Export results to CSV
    if all_transactions:
        csv_filename = f"JPM_form4_{start_date}_to_{end_date}.csv"
        with open(csv_filename, "w", newline='', encoding="utf-8") as csvfile:
            fieldnames = list(all_transactions[0].keys())
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_transactions)
        print(f"💾 Saved {len(all_transactions)} transactions to '{csv_filename}'")
    else:
        print("No transactions found to save.")