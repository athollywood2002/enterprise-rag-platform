# A folder, a question and its sources

Start the application with the [Docker browser quickstart](../README.md#docker-browser-quickstart). This walkthrough shows what to look for at each step. The two screenshots are from an earlier Chromium run of the actual UI with **synthetic model replies**. Its five-file sample differs from the two public quickstart files and the three-file real-model test. Some labels have since changed.

## 1. Check the folder before uploading

Connect at the local URL with the key from your configuration. Choose **Folder on this computer**, enter a source name and select the folder. For the quickstart, choose the repository's `demo/fixtures`. Look for `runbook.txt` and `inventory.csv` in the preview and check the destination. The example below also shows how nested filenames and an excluded binary appear. Nothing is uploaded until you choose **Start ingestion**.

![Synthetic fixture preview showing relative paths, file sizes and an excluded file](images/folder-preview.png)

## 2. Follow the job and recover it after refresh

Click **Start ingestion** once. Each file has a result. Wait for **completed** before asking about it. If a file fails, read the reason in its **Detail** column. To reopen progress, refresh the page, reconnect with your key and choose the same saved job. The example below shows four documents completed and one file skipped.

## 3. Read the evidence behind the answer

Choose **Documents from the selected job**, ask a question and inspect the numbered sources. For the public fixtures, ask “What is the recovery code for demo-router-01 and which team owns it?” Check the runbook for ORION and the inventory for NetworkOps. For a PDF, look at the displayed page and excerpt before accepting the claim.

![Recovered results and cited answer from a synthetic model in the Chromium test](images/folder-results.png)

**Separate real-model example.** In the completed mixed-folder test, the maintenance answer cited page 1 of `procedure.pdf` for **21:15 UTC** and page 2 for **the blue indicator**. David accepted that answer and three others, including the response that the documents gave no purchase price. The harness recorded `FAILED_INCOMPLETE` because log capture was partial. Shutdown was verified. See [all four answers and the limits of the evidence](CURRENT_STATUS.md#what-the-real-browser-run-answered).

## 4. Stop with the library saved

From the repository directory, run the [quickstart stop command](../README.md#4-stop-and-retain-the-library). The named volumes retain the job records and vectors for the next start.

[Server-folder view](images/server-folder.png) · [Mobile view](images/mobile-library.png) · [Original synthetic screenshot run](https://github.com/athollywood2002/enterprise-rag-platform/actions/runs/42099229864) · [Operating guide](folder-library.md)
