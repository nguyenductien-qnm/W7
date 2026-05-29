# Live Smoke Test

Target API: `https://api.nguyenductien.cloud`

Latest verified: May 29, 2026 local time. Demo email
`demo@studybot.com` maps to user `demo`; ready document
`w7-demo-photosynthesis` is in session `default`.

Set variables:

```powershell
$api = "https://api.nguyenductien.cloud"
$user = "demo"
$session = "default"
$headers = @{ "Content-Type" = "application/json"; "X-User-Id" = $user; "X-Session-Id" = $session }
```

1. Login:

```powershell
Invoke-RestMethod "$api/login" -Method POST -Headers $headers -Body (@{ email = "demo@studybot.com" } | ConvertTo-Json)
```

2. List sessions:

```powershell
Invoke-RestMethod "$api/session/list?user_id=$user" -Headers $headers
```

3. Create a session:

```powershell
Invoke-RestMethod "$api/session/create" -Method POST -Headers $headers -Body (@{ user_id = $user; session_name = "W7 smoke" } | ConvertTo-Json)
```

4. List ready documents:

```powershell
Invoke-RestMethod "$api/docs/list?user_id=$user&session_id=$session" -Headers $headers
```

5. Q&A with a ready document:

```powershell
Invoke-RestMethod "$api/ask" -Method POST -Headers $headers -Body (@{
  user_id = $user
  session_id = $session
  selected_doc_ids = @("w7-demo-photosynthesis")
  question = "What are the most important concepts in this document?"
} | ConvertTo-Json)
```

6. Summary returns `testable_concepts`:

```powershell
Invoke-RestMethod "$api/summary" -Method POST -Headers $headers -Body (@{
  user_id = $user
  session_id = $session
  selected_doc_ids = @("w7-demo-photosynthesis")
  question = "Summarize this for an exam."
} | ConvertTo-Json)
```

7. Quiz returns questions:

```powershell
Invoke-RestMethod "$api/quiz" -Method POST -Headers $headers -Body (@{
  user_id = $user
  session_id = $session
  selected_doc_ids = @("w7-demo-photosynthesis")
  feature = "quiz"
  count = 5
  question = "Quiz me."
} | ConvertTo-Json)
```

8. Planner clarification returns `ready:false` when required fields are missing:

```powershell
Invoke-RestMethod "$api/planner/clarify" -Method POST -Headers $headers -Body (@{
  user_id = $user
  session_id = $session
  question = "Make me a study plan."
} | ConvertTo-Json)
```

9. Planner create succeeds with date and hours:

```powershell
Invoke-RestMethod "$api/planner" -Method POST -Headers $headers -Body (@{
  user_id = $user
  session_id = $session
  selected_doc_ids = @("w7-demo-photosynthesis")
  exam_date = "2026-06-20"
  daily_study_hours = 2
  weak_topics = @("CAP theorem", "Replication")
} | ConvertTo-Json)
```

10. Dashboard returns topics:

```powershell
Invoke-RestMethod "$api/dashboard?user_id=$user&session_id=all&days=7" -Headers $headers
```
