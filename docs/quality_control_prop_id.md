 

# 🧩 QUALITY CONTROL (QC)  –  for  Upload and importing CSV File for Indexing

## **Overview**

Integrate a new **Quality Control (QC) ** into the existing system.
The QC  ensures the integrity, format consistency, and linkage of **file numbers** and **property IDs** across all datasets.

It includes both:

* **Automated backend validation and correction logic**
* **An interactive UI dashboard** for reviewing, approving, and correcting records.

---

## ## 1. QC FOR FILE NUMBER FORMAT AND CONSISTENCY

### **a) Padding (Leading Zero) Check**

#### **Objective**

Detect and correct file numbers with unnecessary **leading zeros** in their serial number component.

**Examples of invalid records:**

* `RES-1981-01`
* `RES-1981-041`
* `RES-1981-001`

**Expected correction:**

* `RES-1981-01` → `RES-1981-1`
* `RES-1981-041` → `RES-1981-41`

#### **System Behavior**

* Automatically scan for file numbers whose final numeric segment starts with `0`.
* Provide both **auto-fix** and **manual fix** options.

#### **UI Requirements**

* Display all detected records in a **table view** under a “Padding Check” tab.

* Columns should include:

  * File Number
  * Suggested Fix
  * Status (Pending / Fixed / Approved)
  * Action Buttons (Auto-Fix, Edit, Approve)

* Allow inline editing of file numbers for manual corrections.

* Add a bulk “Fix All” button to automatically apply suggested corrections.

---

### **b) Invalid File Number Year**

#### **Objective**

Ensure all file numbers have a **four-digit year** (e.g., `1982`, `1995`, `2015`).

**Examples of invalid records:**

* `RES-82-56`
* `RES-15-22`

**Expected correction:**

* `RES-82-56` → `RES-1982-56`
* `RES-15-22` → `RES-2015-22`

#### **System Behavior**

* Detect file numbers where the middle section contains only **two digits**.
* Automatically determine the century prefix (e.g., `19xx` for older years, `20xx` for modern ones).
* Offer both automatic and manual correction options.

#### **UI Requirements**

* A “Year Validation” tab in the QC dashboard.
* Display all detected records with columns:

  * File Number
  * Suggested Year Correction
  * Action Buttons (Auto-Fix, Edit)
* Allow quick approval after correction.

---

### **c) File Number Spacing Errors**

#### **Objective**

Identify and correct file numbers containing spaces caused by typographical errors.

**Examples of invalid records:**

* `RES- 1981-1064`
* `RES - 1981 -1065`
* `RES- 1981-10 66`
* `RES -1981 - 1067`

**Expected correction:**

* `RES-1981-1065`

#### **System Behavior**

* Detect any file number with one or more spaces in its structure.
* Auto-fix by removing spaces.

#### **UI Requirements**

* Include a “Spacing Errors” tab in the QC dashboard.
* Highlight detected file numbers in **red or orange** for visibility.
* Provide a “Remove Spaces” button for individual or bulk correction.
* Include manual edit functionality for edge cases.

---

### **d) Temporary File Number (TEMP) Validation**

#### **Objective**

Standardize the notation for temporary file numbers.

**Valid format:**
`RES-1981-99 (TEMP)`

**Invalid variants:**

* `RES-1981-99 (T)`
* `RES-1981-99(T)`
* `RES-1981-99 TEMP`
* `RES-1981-99 T`

**Expected correction:**
All invalid variants → `RES-1981-99 (TEMP)`

#### **System Behavior**

* Identify invalid variants using pattern matching on `(T)`, `(TEMP)`, or “TEMP” without parentheses.
* Normalize to the proper format: **“(TEMP)”** with a space before the parenthesis.

#### **UI Requirements**

* A “TEMP Validation” tab in the QC dashboard.
* Display affected records with:

  * File Number
  * Error Description
  * Suggested Correction
  * Action (Auto-Fix, Edit)
* Provide a confirmation modal for bulk corrections.

---

## ## 2. TRACK, INSERT, AND UPDATE PROPERTY ID (`prop_id`)

### **a) During Data Import**

#### **Objective**

Ensure every file number imported into the system has a consistent **Property ID (`prop_id`)**.

#### **System Behavior**

* When importing records:

  * Automatically assign a new `prop_id` to new file numbers.
  * If a file number already exists, **reuse its existing `prop_id`**.

#### **Error Prevention**

* Prevent creation of duplicate `prop_id`s for the same file number.
* Maintain a cross-reference log of each file number and its assigned property ID.

---

### **b) Property ID Cross-Reference and Synchronization**

#### **Objective**

Before generating or assigning a new `prop_id`, cross-check existing records across related tables.

**Tables to be checked:**

* `CofO`
* `registered_instruments`
* `property_records`

#### **System Behavior**

1. Use the **file number** as the lookup key.
2. If a matching record with a valid `prop_id` is found:

   * Reuse the same `prop_id`.
   * Update the `CofO` table accordingly.
3. If no existing `prop_id` is found:

   * Generate a new one and record it in a central `property_reference` table.

#### **UI Requirements**

* A dedicated **“Property ID Mapping”** tab within the QC dashboard.
* Table columns:

  * File Number
  * Existing Prop ID (if any)
  * Source Table Found
  * Suggested Action (Link / Create New)
* Add a **“Link / Sync”** button for manual confirmation of property ID assignments.

---

## ## 3. QUALITY CONTROL DASHBOARD (UI OVERVIEW)

### **General Design Guidelines**

* The QC dashboard should be accessible via the **Admin Navigation Menu** under “Quality Control”.
* It should contain **tabbed sections** for each QC category:

  1. Padding Check
  2. Year Validation
  3. Spacing Errors
  4. TEMP Validation
  5. Property ID Mapping

### **Common Table Layout**

Each QC tab should follow a consistent table layout with:

* **File Number**
* **Detected Issue / Suggested Fix**
* **Current Status** (Pending, Corrected, Approved)
* **Actions**:

  * **Auto-Fix**
  * **Manual Edit**
  * **Approve**
  * **Bulk Apply**

### **User Interactions**

* Each correction should trigger an **AJAX-based update** (without page reload).
* Include a **search and filter bar** for quick navigation.
* Show **success / error notifications** after each action.
* Use color coding:

  * ⚠️ Yellow → Pending
  * ✅ Green → Fixed
  * ❌ Red → Error / Needs Review

### **Audit and Tracking**

* Every correction (auto or manual) should be logged with:

  * User who performed it
  * Timestamp
  * Original Value
  * Corrected Value

* Provide a small **“History” button** beside each corrected record to view past changes.

---

## ## 4. FUTURE EXTENSIONS (Optional)

* Add **Export to Excel** for QC reports.
* Add **Scheduled QC Tasks** that automatically run validations weekly.
 