# Error Codes

When using API calls to the MiMo model, common error codes and solutions are as follows:

<table>
<colgroup>
<col />
<col style="width: 465px" />
<col style="width: 564px" />
</colgroup>
<thead>
<tr>
<th>**Error Code**</th>
<th>**Causes**</th>
<th>**Solutions**</th>
</tr>
</thead>
<tbody>
<tr>
<td>400 - Invalid Format</td>
<td>Invalid request format</td>
<td><ul><li>Check if the JSON format is correct</li><li>Check if all required parameters are included</li><li>Check if parameter values are within the valid range</li><li>Check if the message format meets the interface requirements</li><li>Check if the model exists</li><li>Check if the fields are entered correctly</li><li>Check multimodal file input for compliance with format, size and other restrictions.</li><li>Check if multimodal file input is publicly accessible</li><li>In multi-turn conversations under thinking mode, the `reasoning_content` field must be fully passed back to the API.</li></ul></td>
</tr>
<tr>
<td>401 - Authentication Fails</td>
<td><ul><li>Missing or invalid API Key, or incorrect Authorization request header format</li><li>API Key that mixes Token Plan and Pay-as-you-go API</li></ul></td>
<td><ul><li>Check if the API key and request header format are correct</li><li>Check if a dedicated Base URL and API Key are used when using the Token Plan</li></ul></td>
</tr>
<tr>
<td>402 - Insufficient Balance</td>
<td>Insufficient account balance</td>
<td>Check your account balance and recharge in a timely manner</td>
</tr>
<tr>
<td>403 - Forbidden Access</td>
<td>The service is currently not available in the current region, or the API Key has been restricted by risk control</td>
<td>Create a new API Key and pay attention to the security of input content</td>
</tr>
<tr>
<td>404 - Not Found</td>
<td>The requested endpoint or model does not support image input capability</td>
<td>Verify that the model / endpoint being used supports image input capability</td>
</tr>
<tr>
<td>421 - Content Filter</td>
<td>Content moderation and blocking</td>
<td>Avoid entering unsafe or sensitive content</td>
</tr>
<tr>
<td>429 - Too Many Requests</td>
<td>Requests are too frequent, or the quota of Token Plan has been exhausted</td>
<td><ul><li>Implement exponential backoff and retry logic, or reduce the request frequency</li><li>Upgrade the Token Plan package or switch to pay-as-you-go API</li></ul></td>
</tr>
<tr>
<td>500 - Server Error</td>
<td>Our server encounters an issue</td>
<td>Please try again later, or contact us for resolution</td>
</tr>
<tr>
<td>503 - Server Overloaded</td>
<td>The server is overloaded due to high traffic</td>
<td>Please try again later</td>
</tr>
</tbody>
</table>
