import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

/**
 * Interface language (English / Hindi).
 *
 * Strings are keyed by their English text: t('Copy') returns the Hindi text when
 * Hindi is selected, and the English key itself when no translation exists, so a
 * missing entry never breaks the UI. Placeholders use {name}: t('{n} pages', { n: 3 }).
 * The choice is stored in this browser only (localStorage 'mrpl.lang').
 *
 * This translates the interface. Model answers follow the selected language through
 * a system instruction sent with each request (backend reliability.language_instruction).
 */

export const LANGUAGES = [
  { id: 'en', label: 'English', short: 'EN' },
  { id: 'hi', label: 'हिन्दी', short: 'हिं' },
];

const HI = {
  // Shell / sidebar / header
  'New chat': 'नई चैट',
  'Chats': 'चैट',
  'Documents': 'दस्तावेज़',
  'Document Assistant': 'दस्तावेज़ सहायक',
  'System Status': 'सिस्टम स्थिति',
  'General Chat': 'सामान्य चैट',
  'Search chats': 'चैट खोजें',
  'Search chats…': 'चैट खोजें…',
  'No conversations yet.': 'अभी कोई बातचीत नहीं।',
  'No chats match your search.': 'आपकी खोज से कोई चैट मेल नहीं खाती।',
  'Show more': 'और दिखाएँ',
  'Loading…': 'लोड हो रहा है…',
  'Delete conversation': 'बातचीत हटाएँ',
  'Rename conversation': 'बातचीत का नाम बदलें',
  'Rename': 'नाम बदलें',
  'Delete': 'हटाएँ',
  'Cancel': 'रद्द करें',
  'Save': 'सहेजें',
  'Close': 'बंद करें',
  'Open sidebar': 'साइडबार खोलें',
  'Close sidebar': 'साइडबार बंद करें',
  'Toggle sidebar': 'साइडबार दिखाएँ/छिपाएँ',
  'Toggle theme': 'थीम बदलें',
  'Light theme': 'लाइट थीम',
  'Dark theme': 'डार्क थीम',
  'Language': 'भाषा',
  'Today': 'आज',
  'Yesterday': 'कल',
  'Previous 7 days': 'पिछले 7 दिन',
  'Older': 'पुराने',
  'Delete this conversation? This cannot be undone.': 'यह बातचीत हटाएँ? इसे वापस नहीं लाया जा सकता।',
  'On-premise · local models': 'ऑन-प्रिमाइस · स्थानीय मॉडल',

  // Chat
  'MRPL Local AI': 'MRPL लोकल AI',
  'Your private, on-premise AI workbench.': 'आपका निजी, ऑन-प्रिमाइस AI वर्कबेंच।',
  'Ask questions, analyze documents, write code, or analyze images.':
    'प्रश्न पूछें, दस्तावेज़ों का विश्लेषण करें, कोड लिखें या चित्रों का विश्लेषण करें।',
  'Data stays on this network. No external AI services are used.':
    'डेटा इसी नेटवर्क में रहता है। कोई बाहरी AI सेवा उपयोग नहीं होती।',
  'Explain a concept': 'कोई अवधारणा समझाएँ',
  'Explain federated learning and why it is useful': 'फ़ेडरेटेड लर्निंग और इसकी उपयोगिता समझाएँ',
  'Analyze an engineering drawing': 'इंजीनियरिंग ड्रॉइंग का विश्लेषण',
  'Attach a drawing, P&ID or photo': 'ड्रॉइंग, P&ID या फ़ोटो संलग्न करें',
  'Write Python code': 'Python कोड लिखें',
  'Parse sensor logs and flag anomalies': 'सेंसर लॉग पढ़ें और असामान्य मान चिह्नित करें',
  'Summarize a document': 'दस्तावेज़ का सारांश',
  'Upload a PDF, scan or text file': 'PDF, स्कैन या टेक्स्ट फ़ाइल अपलोड करें',
  'Loading conversation…': 'बातचीत लोड हो रही है…',
  'Answer ready': 'उत्तर तैयार है',
  'Ask anything…': 'कुछ भी पूछें…',
  'Message': 'संदेश',
  'Send message': 'संदेश भेजें',
  'Send (Enter)': 'भेजें (Enter)',
  'Attach images': 'चित्र संलग्न करें',
  'Attach images (PNG/JPEG, up to {n})': 'चित्र संलग्न करें (PNG/JPEG, अधिकतम {n})',
  'Remove image': 'चित्र हटाएँ',
  'Attachment {n}': 'संलग्नक {n}',
  'Only PNG and JPEG images are supported.': 'केवल PNG और JPEG चित्र समर्थित हैं।',
  'You can attach up to {n} image(s) per message.': 'प्रति संदेश अधिकतम {n} चित्र संलग्न कर सकते हैं।',
  'Think deeper': 'गहराई से सोचें',
  'Thinking on': 'सोच चालू',
  'Think deeper: step-by-step reasoning for hard questions (slower)':
    'गहराई से सोचें: कठिन प्रश्नों के लिए चरणबद्ध तर्क (धीमा)',
  'Think deeper is on: step-by-step reasoning, slower answers':
    'गहराई से सोच चालू है: चरणबद्ध तर्क, धीमे उत्तर',
  'Runs on-premise with local models. Responses can contain mistakes — verify important information.':
    'स्थानीय मॉडलों के साथ ऑन-प्रिमाइस चलता है। उत्तरों में गलतियाँ हो सकती हैं — महत्वपूर्ण जानकारी की जाँच करें।',
  'Copy': 'कॉपी',
  'Copied': 'कॉपी हुआ',
  'Copy code': 'कोड कॉपी करें',
  'Regenerate': 'फिर से बनाएँ',
  'Regenerate response': 'उत्तर फिर से बनाएँ',
  'Regenerate this answer? The messages after it will be replaced.':
    'यह उत्तर फिर से बनाएँ? इसके बाद के संदेश बदल दिए जाएँगे।',
  'Edit': 'संपादित करें',
  'Edit message': 'संदेश संपादित करें',
  'Save & submit': 'सहेजें और भेजें',
  'Editing replaces this message and everything after it.':
    'संपादन से यह संदेश और इसके बाद का सब कुछ बदल जाएगा।',
  'Retry': 'फिर से प्रयास करें',
  'Something went wrong while generating a response.': 'उत्तर बनाते समय कुछ गलत हो गया।',
  'Generating response': 'उत्तर बन रहा है',
  'View attached image {n}': 'संलग्न चित्र {n} देखें',
  'Attached {n}': 'संलग्न {n}',
  'Image preview': 'चित्र पूर्वावलोकन',
  'Close preview': 'पूर्वावलोकन बंद करें',
  'Thinking': 'सोच रहा है',
  'Loading model': 'मॉडल लोड हो रहा है',
  'Loading {model} into GPU memory': '{model} GPU मेमोरी में लोड हो रहा है',
  'Reasoning step by step': 'चरणबद्ध तर्क कर रहा है',
  'Reading the image': 'चित्र पढ़ रहा है',
  'Writing code': 'कोड लिख रहा है',
  'Reading the text in the image': 'चित्र का टेक्स्ट पढ़ रहा है',
  'Analysing pages {pages}': 'पृष्ठ {pages} का विश्लेषण',
  'OCR · recognition confidence': 'OCR · पहचान विश्वसनीयता',
  'Text was read from the image locally with PaddleOCR. Recognition confidence is PaddleOCR\'s own score, not measured accuracy.':
    'चित्र का टेक्स्ट PaddleOCR से स्थानीय रूप से पढ़ा गया। पहचान विश्वसनीयता PaddleOCR का अपना स्कोर है, मापी गई सटीकता नहीं।',
  'Could not load conversations.': 'बातचीत लोड नहीं हो सकीं।',
  'Could not load this conversation.': 'यह बातचीत लोड नहीं हो सकी।',
  'Stop generating': 'उत्तर बनाना रोकें',
  'Stop': 'रोकें',

  // Basis indicator
  'Based on': 'आधार',
  'Based on the document': 'दस्तावेज़ पर आधारित',
  'Based on the attached image': 'संलग्न चित्र पर आधारित',
  'Based on OCR text from the image': 'चित्र के OCR टेक्स्ट पर आधारित',
  'General knowledge (no document)': 'सामान्य ज्ञान (कोई दस्तावेज़ नहीं)',
  'Generated code (not executed)': 'बनाया गया कोड (चलाया नहीं गया)',
  'Check this answer': 'इस उत्तर की जाँच करें',
  'Numbers not found in the source: {values}': 'स्रोत में न मिलने वाली संख्याएँ: {values}',
  'Cites pages that were not provided: {pages}': 'ऐसे पृष्ठों का उल्लेख जो दिए नहीं गए थे: {pages}',
  'The answer claims code was run, but no code is executed here.':
    'उत्तर कहता है कि कोड चलाया गया, पर यहाँ कोई कोड नहीं चलता।',
  'Only part of the document was used': 'दस्तावेज़ का केवल एक भाग उपयोग हुआ',
  'What the answer was based on. This is not a correctness score.':
    'उत्तर किस पर आधारित था। यह सटीकता का स्कोर नहीं है।',

  // Model labels
  'Auto': 'ऑटो',
  'Auto (recommended)': 'ऑटो (अनुशंसित)',
  'Model': 'मॉडल',
  'Choose model': 'मॉडल चुनें',
  'General': 'सामान्य',
  'Coding': 'कोडिंग',
  'Vision': 'विज़न',
  'Image → Code': 'चित्र → कोड',
  'OCR': 'OCR',
  'Document': 'दस्तावेज़',
  'Picks the best local model for each message': 'हर संदेश के लिए सबसे उपयुक्त स्थानीय मॉडल चुनता है',

  // Documents
  'Upload document': 'दस्तावेज़ अपलोड करें',
  'Upload': 'अपलोड',
  'Uploading… {pct}%': 'अपलोड हो रहा है… {pct}%',
  'Processing…': 'प्रोसेस हो रहा है…',
  'Processing page {done} of {total}': 'पृष्ठ {done} / {total} प्रोसेस हो रहा है',
  'Queued': 'कतार में',
  'Processing': 'प्रोसेसिंग',
  'Ready': 'तैयार',
  'Failed': 'विफल',
  'Drop a file here or click to choose': 'फ़ाइल यहाँ छोड़ें या चुनने के लिए क्लिक करें',
  'PDF, DOCX, TXT, PNG or JPG': 'PDF, DOCX, TXT, PNG या JPG',
  'No documents yet. Upload one to get started.': 'अभी कोई दस्तावेज़ नहीं। शुरू करने के लिए एक अपलोड करें।',
  'Select a document to view and ask questions about it.':
    'देखने और प्रश्न पूछने के लिए कोई दस्तावेज़ चुनें।',
  'Summarize': 'सारांश',
  'Summary': 'सारांश',
  'Ask about this document…': 'इस दस्तावेज़ के बारे में पूछें…',
  'Ask': 'पूछें',
  'Extracted text': 'निकाला गया टेक्स्ट',
  'Pages': 'पृष्ठ',
  'pages': 'पृष्ठ',
  'Uploaded': 'अपलोड किया गया',
  'Delete document': 'दस्तावेज़ हटाएँ',
  'Delete this document? This cannot be undone.': 'यह दस्तावेज़ हटाएँ? इसे वापस नहीं लाया जा सकता।',
  'This document is still being processed. You can ask questions when it is ready.':
    'यह दस्तावेज़ अभी प्रोसेस हो रहा है। तैयार होने पर प्रश्न पूछ सकते हैं।',
  'Processing failed': 'प्रोसेसिंग विफल',
  'Some pages were read by the vision model because OCR confidence was low. Check them against the original.':
    'कुछ पृष्ठ कम OCR विश्वसनीयता के कारण विज़न मॉडल से पढ़े गए। उन्हें मूल से मिलाएँ।',
  'Pages not covered: {n}': 'शामिल न किए गए पृष्ठ: {n}',
  'Only the most relevant sections of this long document were used.':
    'इस लंबे दस्तावेज़ के केवल सबसे प्रासंगिक भाग उपयोग हुए।',
  'Could not load documents.': 'दस्तावेज़ लोड नहीं हो सके।',
  'Back to documents': 'दस्तावेज़ों पर वापस',

  // Dashboard
  'Refresh': 'रीफ़्रेश',
  'Last checked': 'अंतिम जाँच',
  'Healthy': 'स्वस्थ',
  'Degraded': 'आंशिक',
  'Down': 'बंद',
  'Limited': 'सीमित',
  'Services': 'सेवाएँ',
  'Models': 'मॉडल',
  'Usage': 'उपयोग',
  'GPU & power': 'GPU और पावर',
  'Requests': 'अनुरोध',
  'Average response time': 'औसत उत्तर समय',
  'Errors': 'त्रुटियाँ',
  'Loaded in GPU': 'GPU में लोड',
  'Not loaded': 'लोड नहीं',
  'Could not load system status.': 'सिस्टम स्थिति लोड नहीं हो सकी।',
  'Helpful': 'उपयोगी',
  'Not helpful': 'उपयोगी नहीं',
  'Last 14 days': 'पिछले 14 दिन',
  'Per model': 'मॉडल अनुसार',
  'Regenerated': 'फिर से बनाए गए',
  'User ratings': 'उपयोगकर्ता रेटिंग',
  '{pct}% rated helpful': '{pct}% ने उपयोगी बताया',
  'No ratings yet': 'अभी कोई रेटिंग नहीं',
  'Requests per day, last 14 days: {n} in total': 'पिछले 14 दिनों में प्रति दिन अनुरोध: कुल {n}',
  '{n} requests': '{n} अनुरोध',
  '{n} failed': '{n} विफल',
  'avg': 'औसत',
  'peak {n} per day': 'अधिकतम {n} प्रति दिन',
  '{n} request(s) failed in local OCR before any model ran.': '{n} अनुरोध किसी मॉडल के चलने से पहले स्थानीय OCR में विफल हुए।',
  '{n} document(s) failed during text extraction.': '{n} दस्तावेज़ टेक्स्ट निकालते समय विफल हुए।',
  'User ratings are opinions from the 👍/👎 buttons, not a measured accuracy.': 'उपयोगकर्ता रेटिंग 👍/👎 बटनों से दी गई राय है, मापी गई सटीकता नहीं।',
  '{n} older requests were reconstructed from stored answers (no timing).': '{n} पुराने अनुरोध सहेजे गए उत्तरों से पुनर्निर्मित किए गए (समय के बिना)।',
  'Database': 'डेटाबेस',
  'Disk space': 'डिस्क स्थान',
  '{free} GB free of {total} GB': '{total} GB में से {free} GB खाली',
  'Deep checks': 'गहन जाँच',
  'Runs a real test: OCR reads a generated line of text, or a model answers a one-word prompt. Loads the model into GPU memory (can take 10–60 s) and is not counted as usage.':
    'वास्तविक परीक्षण चलाता है: OCR एक बनाई गई पंक्ति पढ़ता है, या मॉडल एक-शब्द प्रश्न का उत्तर देता है। मॉडल GPU मेमोरी में लोड होता है (10–60 सेकंड लग सकते हैं) और इसे उपयोग में नहीं गिना जाता।',
  'Run test': 'परीक्षण चलाएँ',
  'Running…': 'चल रहा है…',
  'Passed': 'सफल',
  'A table or multi-column layout was detected; the OCR text was rebuilt as a table or columns and may still be out of order.':
    'तालिका या बहु-स्तंभ लेआउट मिला; OCR टेक्स्ट को तालिका या स्तंभों में पुनर्निर्मित किया गया, फिर भी क्रम गलत हो सकता है।',

  // Sidebar / header (continued)
  'Chat': 'चैट',
  'Navigation': 'नेविगेशन',
  'Sovereign AI Workbench': 'सॉवरेन AI वर्कबेंच',
  'Search chats and messages': 'चैट और संदेश खोजें',
  'Search conversations': 'बातचीत खोजें',
  'No matching chats.': 'कोई मेल खाती चैट नहीं।',
  'All inference runs on local models inside the company network': 'सारा इन्फ़रेंस कंपनी नेटवर्क के अंदर स्थानीय मॉडलों पर चलता है',
  'On-premise · local models only': 'ऑन-प्रिमाइस · केवल स्थानीय मॉडल',
  'On-premise': 'ऑन-प्रिमाइस',
  'Inference runs on local models; no external AI APIs': 'इन्फ़रेंस स्थानीय मॉडलों पर चलता है; कोई बाहरी AI API नहीं',
  'System theme': 'सिस्टम थीम',
  'click to change': 'बदलने के लिए क्लिक करें',
  'Change theme': 'थीम बदलें',
  'Untitled': 'शीर्षकहीन',
  'Conversation title': 'बातचीत का शीर्षक',
  'Save title': 'शीर्षक सहेजें',
  'Cancel rename': 'नाम बदलना रद्द करें',
  'Document Q&A': 'दस्तावेज़ प्रश्नोत्तर',
  'this conversation': 'यह बातचीत',
  'Delete "{title}"? This also removes its images.': '"{title}" हटाएँ? इसके चित्र भी हट जाएँगे।',
  'The local AI service did not return a response.': 'स्थानीय AI सेवा ने कोई उत्तर नहीं दिया।',

  // Chat (continued)
  'Attachment': 'संलग्नक',
  'Could not read image file.': 'चित्र फ़ाइल पढ़ी नहीं जा सकी।',
  'Unsupported image file.': 'असमर्थित चित्र फ़ाइल।',
  'model': 'मॉडल',
  'Thinking step by step': 'चरणबद्ध सोच रहा है',
  'Reading the image with Qwen2.5-VL 7B': 'Qwen2.5-VL 7B से चित्र पढ़ रहा है',
  'Writing code with Qwen2.5-Coder 7B': 'Qwen2.5-Coder 7B से कोड लिख रहा है',
  'recognition confidence': 'पहचान विश्वसनीयता',
  'Copy text': 'टेक्स्ट कॉपी करें',
  'Document text · OCR': 'दस्तावेज़ टेक्स्ट · OCR',
  'Vision + OCR': 'विज़न + OCR',
  'Selected manually': 'मैन्युअल रूप से चुना गया',
  'Model: Auto lets the workbench pick the best local model': 'मॉडल: ऑटो में वर्कबेंच सबसे उपयुक्त स्थानीय मॉडल चुनता है',

  // Basis (continued)
  'Based on uploaded document': 'अपलोड किए गए दस्तावेज़ पर आधारित',
  'Based on provided image': 'दिए गए चित्र पर आधारित',
  'Based on text read from the provided image (OCR)': 'दिए गए चित्र से पढ़े गए टेक्स्ट (OCR) पर आधारित',
  'General AI response': 'सामान्य AI उत्तर',
  'Generated code — not executed': 'बनाया गया कोड — चलाया नहीं गया',
  'Not found in the provided document': 'दिए गए दस्तावेज़ में नहीं मिला',
  'Cannot be determined from the provided image': 'दिए गए चित्र से निर्धारित नहीं किया जा सकता',
  'Not found in the text read from the image': 'चित्र से पढ़े गए टेक्स्ट में नहीं मिला',
  'Values not found in the document: {v}': 'दस्तावेज़ में न मिलने वाले मान: {v}',
  'Values not found in the OCR text: {v}': 'OCR टेक्स्ट में न मिलने वाले मान: {v}',
  'Cited pages not given to the model: {v}': 'उल्लिखित पृष्ठ जो मॉडल को नहीं दिए गए थे: {v}',
  'The answer says the code was run or tested, but the workbench did not execute it.':
    'उत्तर कहता है कि कोड चलाया या परखा गया, पर वर्कबेंच ने उसे नहीं चलाया।',
  'Shows what this answer was based on. It does not guarantee that the answer is correct.':
    'दिखाता है कि यह उत्तर किस पर आधारित था। यह उत्तर के सही होने की गारंटी नहीं देता।',
  'Automatic check against the source (not a model judgement)': 'स्रोत से स्वचालित जाँच (मॉडल का निर्णय नहीं)',

  // Documents (continued)
  'Loading documents…': 'दस्तावेज़ लोड हो रहे हैं…',
  'No documents uploaded yet.': 'अभी कोई दस्तावेज़ अपलोड नहीं हुआ।',
  'Upload a PDF, TXT or image file above to begin.': 'शुरू करने के लिए ऊपर PDF, TXT या चित्र फ़ाइल अपलोड करें।',
  'Uploaded Documents ({n})': 'अपलोड किए गए दस्तावेज़ ({n})',
  '{n} chars': '{n} अक्षर',
  'Delete document "{name}"?': 'दस्तावेज़ "{name}" हटाएँ?',
  "Invalid file type '{ext}'. Only PDF, TXT, PNG and JPG/JPEG files are supported.":
    "अमान्य फ़ाइल प्रकार '{ext}'। केवल PDF, TXT, PNG और JPG/JPEG फ़ाइलें समर्थित हैं।",
  'The selected file is empty.': 'चुनी गई फ़ाइल खाली है।',
  'File size exceeds 15MB limit.': 'फ़ाइल का आकार 15MB सीमा से अधिक है।',
  '"{name}" processed with local OCR ({n} page(s)).': '"{name}" स्थानीय OCR से प्रोसेस हुई ({n} पृष्ठ)।',
  '"{name}" uploaded and text extracted successfully!': '"{name}" अपलोड हुई और टेक्स्ट सफलतापूर्वक निकाला गया!',
  'Failed to process document on server.': 'सर्वर पर दस्तावेज़ प्रोसेस नहीं हो सका।',
  'An error occurred during upload.': 'अपलोड के दौरान त्रुटि हुई।',
  'Processing status': 'प्रोसेसिंग स्थिति',
  'Uploading {pct}%': 'अपलोड हो रहा है {pct}%',
  'Uploaded': 'अपलोड हुआ',
  'Processing: reading text, OCR for scanned pages': 'प्रोसेसिंग: टेक्स्ट पढ़ना, स्कैन किए पृष्ठों के लिए OCR',
  'Upload progress': 'अपलोड प्रगति',
  'Scanned pages take about 10–20 seconds each to process.': 'हर स्कैन किए पृष्ठ में लगभग 10–20 सेकंड लगते हैं।',
  'Click to upload': 'अपलोड करने के लिए क्लिक करें',
  'or drag & drop file here': 'या फ़ाइल यहाँ खींचकर छोड़ें',
  "PDF, TXT, PNG or JPG (Max 15MB) · scans are OCR'd locally": 'PDF, TXT, PNG या JPG (अधिकतम 15MB) · स्कैन का OCR स्थानीय रूप से होता है',
  'Language of the text in scanned pages and images': 'स्कैन किए पृष्ठों और चित्रों में टेक्स्ट की भाषा',
  'OCR language': 'OCR भाषा',
  'Hide document list': 'दस्तावेज़ सूची छिपाएँ',
  'Show document list': 'दस्तावेज़ सूची दिखाएँ',
  'Visual analysis used page(s) {pages} of {total}. Mention "page N" in your question to look at another page.':
    'दृश्य विश्लेषण में {total} में से पृष्ठ {pages} उपयोग हुए। दूसरा पृष्ठ देखने के लिए प्रश्न में "page N" लिखें।',
  '{n} later page(s) were not analysed (limit per question). Ask about "pages N–M" to see them.':
    'बाद के {n} पृष्ठों का विश्लेषण नहीं हुआ (प्रति प्रश्न सीमा)। उन्हें देखने के लिए "pages N–M" के बारे में पूछें।',
  'Long document: the {used} most relevant of {total} sections were used (pages {pages}).':
    'लंबा दस्तावेज़: {total} में से {used} सबसे प्रासंगिक भाग उपयोग हुए (पृष्ठ {pages})।',
  'Long document: the {used} most relevant of {total} sections were used.':
    'लंबा दस्तावेज़: {total} में से {used} सबसे प्रासंगिक भाग उपयोग हुए।',
  'Long document: {used} sections spread across the document were used.':
    'लंबा दस्तावेज़: पूरे दस्तावेज़ में फैले {used} भाग उपयोग हुए।',
  'Answer based on the first {used} of {total} characters (model context limit).':
    'उत्तर {total} में से पहले {used} अक्षरों पर आधारित है (मॉडल संदर्भ सीमा)।',
  'The model read the first {used} of {total} characters (model context window limit).':
    'मॉडल ने {total} में से पहले {used} अक्षर पढ़े (मॉडल संदर्भ सीमा)।',
  'Regenerate failed: {error}': 'फिर से बनाना विफल: {error}',
  'Failed to get an answer from the local AI.': 'स्थानीय AI से उत्तर नहीं मिल सका।',
  'Ask anything about': 'इसके बारे में कुछ भी पूछें:',
  'Answers come from the document\'s text; visual questions ("what does the drawing on page 2 show?") use the vision model.':
    'उत्तर दस्तावेज़ के टेक्स्ट से आते हैं; दृश्य प्रश्न ("पृष्ठ 2 की ड्रॉइंग क्या दिखाती है?") विज़न मॉडल का उपयोग करते हैं।',
  'Start a new Q&A conversation for this document': 'इस दस्तावेज़ के लिए नई प्रश्नोत्तर बातचीत शुरू करें',
  'New Q&A conversation': 'नई प्रश्नोत्तर बातचीत',
  'Ask about {name}…': '{name} के बारे में पूछें…',
  'Answers are generated locally from this document. Verify important values against the original.':
    'उत्तर इस दस्तावेज़ से स्थानीय रूप से बनाए जाते हैं। महत्वपूर्ण मानों को मूल से मिलाएँ।',
  'Select a document': 'दस्तावेज़ चुनें',
  'Choose an uploaded file from the left panel to review its contents, ask questions, or generate a Word report.':
    'सामग्री देखने, प्रश्न पूछने या Word रिपोर्ट बनाने के लिए बाएँ पैनल से अपलोड की गई फ़ाइल चुनें।',
  'Processing document…': 'दस्तावेज़ प्रोसेस हो रहा है…',
  'The document could not be processed.': 'दस्तावेज़ प्रोसेस नहीं हो सका।',
  'Reading page {done} of {total}. Scanned pages take a few seconds each.':
    'पृष्ठ {done} / {total} पढ़ा जा रहा है। हर स्कैन किए पृष्ठ में कुछ सेकंड लगते हैं।',
  'Extracting text. Scanned pages are read with local OCR.': 'टेक्स्ट निकाला जा रहा है। स्कैन किए पृष्ठ स्थानीय OCR से पढ़े जाते हैं।',
  'Remove': 'हटाएँ',
  'Only the first {kept} of {total} extracted characters were kept (DOCUMENT_MAX_CHARS).':
    'निकाले गए {total} अक्षरों में से केवल पहले {kept} रखे गए (DOCUMENT_MAX_CHARS)।',
  'Table or multi-column layout detected: tables and columns were reconstructed from the OCR layout. Check tables against the original.':
    'तालिका या बहु-स्तंभ लेआउट मिला: तालिकाएँ और स्तंभ OCR लेआउट से पुनर्निर्मित किए गए। तालिकाओं को मूल से मिलाएँ।',
  'Low OCR recognition confidence: the scan may be poor quality, rotated, handwritten or in a different language. Verify important values against the original.':
    'कम OCR पहचान विश्वसनीयता: स्कैन खराब, घुमा हुआ, हस्तलिखित या अन्य भाषा में हो सकता है। महत्वपूर्ण मानों को मूल से मिलाएँ।',
  '{n} page(s) had low OCR confidence (e.g. handwriting or a poor scan) and were transcribed by the vision model instead. A vision model can misread or invent text: verify against the original.':
    '{n} पृष्ठों की OCR विश्वसनीयता कम थी (जैसे हस्तलेख या खराब स्कैन), इसलिए उन्हें विज़न मॉडल ने लिखा। विज़न मॉडल टेक्स्ट गलत पढ़ या गढ़ सकता है: मूल से मिलाएँ।',
  "{n} scanned page(s) were not OCR'd: the limit is {max} OCR pages per PDF (OCR_MAX_PDF_PAGES).":
    '{n} स्कैन किए पृष्ठों का OCR नहीं हुआ: प्रति PDF सीमा {max} OCR पृष्ठ है (OCR_MAX_PDF_PAGES)।',
  'Failed to generate summary from local AI.': 'स्थानीय AI से सारांश नहीं बन सका।',
  'Error generating document summary.': 'दस्तावेज़ सारांश बनाने में त्रुटि।',
  'Failed to generate Word report.': 'Word रिपोर्ट नहीं बन सकी।',
  'Failed to download Word report.': 'Word रिपोर्ट डाउनलोड नहीं हो सकी।',
  'Text extracted; ready for questions and summaries': 'टेक्स्ट निकाला गया; प्रश्नों और सारांश के लिए तैयार',
  "Text extracted locally with PaddleOCR. Recognition confidence is PaddleOCR's own score for the text it found; it is not a measured accuracy and can be high even when text is misread or missing.":
    'टेक्स्ट PaddleOCR से स्थानीय रूप से निकाला गया। पहचान विश्वसनीयता PaddleOCR का अपना स्कोर है; यह मापी गई सटीकता नहीं है और टेक्स्ट गलत पढ़े जाने पर भी अधिक हो सकती है।',
  '{n} page(s)': '{n} पृष्ठ',
  'Text was capped at {n} characters': 'टेक्स्ट {n} अक्षरों पर सीमित किया गया',
  'Capped at {n} chars': '{n} अक्षरों पर सीमित',
  'Generate AI Summary': 'AI सारांश बनाएँ',
  'Generate Summary': 'सारांश बनाएँ',
  'Regenerate Summary': 'सारांश फिर से बनाएँ',
  'Export and download Word report (.docx)': 'Word रिपोर्ट (.docx) निर्यात और डाउनलोड करें',
  'Export DOCX': 'DOCX निर्यात करें',
  'Are you sure you want to delete "{name}"?': 'क्या आप "{name}" हटाना चाहते हैं?',
  'Delete this document': 'यह दस्तावेज़ हटाएँ',
  'AI Executive Summary': 'AI कार्यकारी सारांश',
  'Extracted Text': 'निकाला गया टेक्स्ट',
  'Generating executive summary with the local Qwen model…': 'स्थानीय Qwen मॉडल से कार्यकारी सारांश बन रहा है…',
  'Processed on this machine with no external cloud calls': 'इसी मशीन पर प्रोसेस, कोई बाहरी क्लाउड कॉल नहीं',
  'Try Again': 'फिर से प्रयास करें',
  'Executive Summary': 'कार्यकारी सारांश',
  'No summary generated yet': 'अभी कोई सारांश नहीं बना',
  'Click "Generate Summary" to have the local AI summarize this document.':
    'इस दस्तावेज़ का सारांश स्थानीय AI से बनवाने के लिए "सारांश बनाएँ" पर क्लिक करें।',
  'Raw Extracted Content ({n} characters)': 'निकाली गई मूल सामग्री ({n} अक्षर)',
  'No text available.': 'कोई टेक्स्ट उपलब्ध नहीं।',

  // Dashboard (continued)
  'Usage Dashboard': 'उपयोग डैशबोर्ड',
  'How the local models are being used. Counts are requests, not a measure of answer quality.':
    'स्थानीय मॉडलों का उपयोग कैसे हो रहा है। गिनती अनुरोधों की है, उत्तर की गुणवत्ता का माप नहीं।',
  'Loading usage…': 'उपयोग लोड हो रहा है…',
  'No model usage recorded yet.': 'अभी कोई मॉडल उपयोग दर्ज नहीं।',
  'Total queries': 'कुल प्रश्न',
  'Successful': 'सफल',
  'Model usage': 'मॉडल उपयोग',
  'Routing distribution': 'रूटिंग वितरण',
  'Recorded since {date} · includes chat, document Q&A and summaries · failed = the model call did not complete.':
    '{date} से दर्ज · चैट, दस्तावेज़ प्रश्नोत्तर और सारांश शामिल · विफल = मॉडल कॉल पूरी नहीं हुई।',
  'Django Backend': 'Django बैकएंड',
  'OCR Engine': 'OCR इंजन',
  'Cannot be checked while the backend is unreachable.': 'बैकएंड उपलब्ध न होने पर जाँच नहीं हो सकती।',
  'Lightweight checks only: no model is loaded and no inference is run.': 'केवल हल्की जाँच: कोई मॉडल लोड नहीं होता और कोई इन्फ़रेंस नहीं चलता।',
  'Check Status': 'स्थिति जाँचें',
  'Checking…': 'जाँच हो रही है…',
  'Version {v}': 'संस्करण {v}',
  '{used} / {total} GB used': '{used} / {total} GB उपयोग में',
  'on mains power': 'बिजली (AC) पर',
  'on battery': 'बैटरी पर',
  'Model Health': 'मॉडल स्वास्थ्य',
  '{size} on disk': 'डिस्क पर {size}',
  'loaded in GPU memory ({size})': 'GPU मेमोरी में लोड ({size})',
  'Last successful use:': 'अंतिम सफल उपयोग:',
  'Not used yet': 'अभी उपयोग नहीं हुआ',
  'Just now': 'अभी-अभी',
  '{n} min ago': '{n} मिनट पहले',
  '{n} h ago': '{n} घंटे पहले',
  '"Ready" means the model is installed in the local Ollama service. It does not measure answer quality. Models load into the 8 GB GPU one at a time when first used.':
    '"तैयार" का अर्थ है मॉडल स्थानीय Ollama सेवा में इंस्टॉल है। यह उत्तर की गुणवत्ता नहीं मापता। पहली बार उपयोग पर मॉडल 8 GB GPU में एक-एक करके लोड होते हैं।',
  'Checked {time}': '{time} पर जाँचा गया',
  'Unavailable': 'अनुपलब्ध',
  'Unknown': 'अज्ञात',
  'Offline': 'ऑफ़लाइन',
  'Online': 'ऑनलाइन',
  'Connected': 'कनेक्टेड',
  'Misconfigured': 'गलत कॉन्फ़िगरेशन',
  'Not installed': 'इंस्टॉल नहीं',
  'Models missing': 'मॉडल अनुपलब्ध',
  'Not detected': 'नहीं मिला',
  'General Reasoning': 'सामान्य तर्क',
  'Code Generation': 'कोड निर्माण',
  'Vision / Multimodal': 'विज़न / मल्टीमॉडल',
};

const DICTS = { hi: HI };
const STORAGE_KEY = 'mrpl.lang';

function initialLang() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && LANGUAGES.some((l) => l.id === saved)) return saved;
  } catch { /* storage unavailable */ }
  return 'en';
}

export function translate(lang, key, vars) {
  let text = DICTS[lang]?.[key] ?? key;
  if (vars) {
    text = text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
  }
  return text;
}

const I18nContext = createContext({ lang: 'en', setLang: () => {}, t: (k, v) => translate('en', k, v) });

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(initialLang);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next) => {
    setLangState(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
  }, []);

  const t = useCallback((key, vars) => translate(lang, key, vars), [lang]);
  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
