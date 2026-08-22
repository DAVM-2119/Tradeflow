# TradeFlow — Intelligent Logistics & Freight Matching Platform

TradeFlow is a digital freight marketplace and logistics optimization platform connecting cargo owners, transporters, and freight forwarders along Ethiopia's principal trade corridors (Djibouti Port → Modjo Dry Port → regional hubs).

---

## Technical Stack & Architecture

- **Backend Framework**: Python 3.13, Django 5.x, Django REST Framework
- **Authentication**: JWT (JSON Web Tokens via `djangorestframework-simplejwt`)
- **Database**: PostgreSQL (managed locally)
- **Cache & Message Broker**: Redis (managed locally)
- **Asynchronous Tasks**: Celery & Redis
- **Real-Time WebSockets**: Django Channels & Redis
- **Documentation**: OpenAPI 3.0 via `drf-spectacular`

---

## API Endpoints

### 1. Authentication (`/api/v1/auth/`)
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register/` | Register user (`SHIPPER`, `TRANSPORTER`, `DRIVER`, etc.) and initialize profile | Public |
| `POST` | `/api/v1/auth/login/` | Obtain JWT token pair (`access` & `refresh`) | Public |
| `POST` | `/api/v1/auth/refresh/` | Obtain new access token using refresh token | Public |
| `GET` | `/api/v1/auth/me/` | Retrieve authenticated user profile & role details | `Bearer <token>` |
| `PATCH`| `/api/v1/auth/me/` | Update user profile fields | `Bearer <token>` |

### 2. Marketplace, Fleet & Onboarding (`/api/v1/`)
| Method | Endpoint | Description | Auth / Role Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/transporters/` | List marketplace transporters (Admins see all; Shippers see verified) | Authenticated |
| `GET` | `/api/v1/transporters/me/` | View current transporter profile and verification status | Transporter |
| `GET/POST` | `/api/v1/transporters/me/vehicles/` | List or add fleet vehicles owned by transporter | Transporter |
| `GET/PATCH/DELETE` | `/api/v1/transporters/me/vehicles/{id}/` | Manage fleet vehicle | Vehicle Owner / Admin |
| `POST` | `/api/v1/transporters/{id}/verification/` | Verify or suspend a transporter with reason | **Admin Only** |
| `GET` | `/api/v1/transporters/{id}/verification/history/` | View verification audit trail for transporter | **Admin Only** |
| `GET/POST` | `/api/v1/ratings/` | List and submit post-trip marketplace ratings | Authenticated |

### 3. Cargo Loads & Spot Market Bidding (`/api/v1/`)
| Method | Endpoint | Description | Auth / Role Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/loads/` | List spot market loads (filter by `origin`, `destination`, `required_vehicle_type`, `status`) | Authenticated |
| `POST` | `/api/v1/loads/` | Post a new cargo load | Shipper / Admin |
| `GET/PATCH` | `/api/v1/loads/{id}/` | View or update cargo load details | Load Owner / Admin |
| `POST` | `/api/v1/loads/{id}/cancel/` | Cancel a posted cargo load | Load Owner / Admin |
| `GET` | `/api/v1/loads/{id}/bids/` | View bids submitted on a cargo load | Load Owner / Transporter / Admin |
| `POST` | `/api/v1/loads/{id}/bids/` | Submit a spot market bid on a load | **VERIFIED Transporters Only** |
| `POST` | `/api/v1/bids/{id}/accept/` | Accept a winning bid (Atomic transaction) | Load Owner Shipper / Admin |
| `POST` | `/api/v1/bids/{id}/withdraw/` | Withdraw a submitted bid | Transporter Owner |
| `GET` | `/api/v1/bids/me/` | List all bids submitted by authenticated transporter | Transporter |

### 4. Shipments & Real-Time GPS Tracking (`/api/v1/`)
| Method | Endpoint | Description | Auth / Role Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/shipments/` | List active corridor shipments | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/` | Get shipment details with latest location & status | Shipment Participant / Admin |
| `POST` | `/api/v1/shipments/{id}/assign-driver/` | Assign a driver to an active shipment | Transporter Owner / Admin |
| `POST` | `/api/v1/shipments/{id}/status/` | Update shipment status (`AT_PICKUP`, `IN_TRANSIT`, `DELIVERED`) with milestone log | Assigned Driver / Transporter / Admin |
| `POST` | `/api/v1/shipments/{id}/location/` | Submit GPS telemetry ping for shipment in transit | Assigned Driver / Transporter / Admin |
| `GET` | `/api/v1/shipments/{id}/tracking/` | View complete GPS location history & milestone audit trail | Shipment Participant / Admin |

### 5. Document Management & Digital Proof of Delivery (`/api/v1/`)
| Method | Endpoint | Description | Auth / Role Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/shipments/{id}/documents/` | List documents associated with a shipment | Shipment Participant / Admin |
| `POST` | `/api/v1/shipments/{id}/documents/` | Upload logistics document (Waybill, Customs Release, etc.) | Shipment Participant / Admin |
| `GET` | `/api/v1/documents/{id}/` | Retrieve document metadata | Shipment Participant / Admin |
| `GET` | `/api/v1/documents/{id}/download/` | Protected document download (returns FileResponse) | Shipment Participant / Admin |
| `DELETE` | `/api/v1/documents/{id}/` | Delete shipment document | Document Uploader / Admin |
| `GET` | `/api/v1/shipments/{id}/pod/` | Get digital Proof of Delivery (e-POD) details | Shipment Participant / Admin |
| `POST` | `/api/v1/shipments/{id}/pod/` | Submit digital Proof of Delivery (e-POD) | Driver / Transporter / Admin |
| `POST` | `/api/v1/pod/{id}/confirm/` | Confirm e-POD delivery (`CONFIRMED`) | Shipper Load Owner / Admin |
| `POST` | `/api/v1/pod/{id}/dispute/` | Dispute e-POD delivery (`DISPUTED` with reason) | Shipper Load Owner / Admin |

### 6. Payments & Freight Settlement (`/api/v1/`)
| Method | Endpoint | Description | Auth / Role Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/payments/initiate/` | Initiate payment with idempotency key enforcement | Shipper Load Owner / Admin |
| `GET` | `/api/v1/payments/` | List payment transactions | Participant / Admin |
| `GET` | `/api/v1/payments/{id}/` | Get payment transaction details | Participant / Admin |
| `POST` | `/api/v1/payments/{id}/verify/` | Verify payment status with payment provider | Participant / Admin |
| `POST` | `/api/v1/payments/{id}/reconcile/` | Perform payment reconciliation check | **Admin Only** |
| `GET` | `/api/v1/shipments/{id}/payments/` | Get payment transactions for a specific shipment | Participant / Admin |
| `GET` | `/api/v1/invoices/` | List freight invoices | Participant / Admin |
| `GET` | `/api/v1/invoices/{id}/` | Get freight invoice details | Participant / Admin |
| `POST` | `/api/v1/settlements/create/` | Create freight settlement for completed shipment | Participant / Admin |
| `GET` | `/api/v1/settlements/` | List freight settlements | Participant / Admin |
| `GET` | `/api/v1/settlements/{id}/` | Get freight settlement details | Participant / Admin |
| `POST` | `/api/v1/settlements/{id}/dispute/` | Raise a payment settlement dispute | Participant / Admin |
| `GET` | `/api/v1/payouts/` | List transporter payouts | Transporter Owner / Admin |
| `GET` | `/api/v1/payouts/{id}/` | Get payout details | Transporter Owner / Admin |
| `POST` | `/api/v1/payouts/{id}/process/` | Process transporter payout transfer | **Admin Only** |

### 7. Offline-First Synchronization & Incident Reporting (`/api/v1/`)
| Method | Endpoint | Description | Auth / Role Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/sync/events/` | Batch sync offline events (`GPS_UPDATE`, `WAYPOINT_CHECKIN`, `INCIDENT_REPORT`) with idempotency protection | Assigned Driver / Transporter / Admin |
| `GET` | `/api/v1/shipments/{id}/incidents/` | List driver incident reports logged for a shipment | Shipment Participant / Admin |

### 8. Route Optimization, ETA & Fuel Analytics (`/api/v1/`)
| Method | Endpoint | Description | Auth / Role Required |
| :--- | :--- | :--- | :--- |
| `POST/GET` | `/api/v1/shipments/{id}/route/` | Plan new route or retrieve active route with ordered waypoints | Shipment Participant / Admin |
| `POST` | `/api/v1/shipments/{id}/route/recalculate/` | Recalculate route while preserving historical audit records | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/route/analytics/` | View comprehensive route efficiency analytics | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/eta/` | Calculate live ETA based on real-time GPS progress | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/fuel/` | Get fuel consumption and cost analytics (ETB) | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/deviation/` | Check route deviation status (`ON_ROUTE`, `DEVIATED`) | Shipment Participant / Admin |

### 9. AI Predictive Logistics & Risk Intelligence (`/api/v1/`)
| Method | Endpoint | Description | Auth / Role Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/shipments/{id}/predictions/` | Consolidated predictive logistics & operational risk summary dashboard | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/predictions/eta/` | Predict ETA delay minutes, delay probability, risk score, and confidence | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/predictions/risk/` | Shipment delay-risk scoring with explainable contributing factors | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/predictions/route-risk/` | Route risk score and major corridor risk factors | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/predictions/fuel/` | Predict fuel consumption (L) and fuel cost (ETB) | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/predictions/incident-risk/` | Incident risk prediction based on driver history and route deviation | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/predictions/history/` | View paginated historical prediction audit trail | Shipment Participant / Admin |

### 10. Dynamic Pricing & Freight Market Intelligence (`/api/v1/`)
| Method | Endpoint | Description | Auth / Role Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/shipments/{id}/pricing/` | Calculate and persist decision-support freight price recommendations (minimum, recommended, maximum) | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/pricing/history/` | View paginated historical price recommendation audit records | Shipment Participant / Admin |
| `GET` | `/api/v1/shipments/{id}/pricing/market/` | View corridor market intelligence and demand/supply statistics | Shipment Participant / Admin |
| `GET` | `/api/v1/pricing/strategies/` | List active pricing strategies and rate parameters | Admin Only |

---

## Business & Security Rules

- **Spot Market Bidding Eligibility**: Only `VERIFIED` transporters can submit bids (`IsTransporterVerified` & `VerificationService.can_accept_load()`). Unverified (`PENDING` or `SUSPENDED`) transporters receive `403 Forbidden`.
- **Atomic Bid Acceptance**: Executed via `transaction.atomic()`. Accepting a bid atomically updates load status to `ASSIGNED`, assigns winning transporter & vehicle, marks winning bid `ACCEPTED`, rejects competing bids, and initializes a `Shipment` record with a unique tracking number (`TRK-...`).
- **Real-Time GPS & Milestone Auditing**: Status transitions log `ShipmentMilestone` records. Telemetry pings capture latitude, longitude, speed (km/h), heading, and location name.
- **Document Management & File Validation**: Maximum file size 10MB; allowed extensions `.pdf`, `.png`, `.jpg`, `.jpeg`. Executables (`.exe`, `.sh`, `.bat`, etc.) rejected with `400 Bad Request`. Computes SHA-256 checksum deterministically.
- **Protected Downloads**: Direct public file links are restricted; documents are downloaded via protected endpoint `GET /api/v1/documents/{id}/download/` enforcing participant authorization checks (`403 Forbidden` for non-participants).
- **Digital Proof of Delivery (e-POD)**: Submitting an e-POD creates a `ProofOfDelivery` record in `SUBMITTED` state, automatically sets shipment status to `DELIVERED`, and logs a delivery `ShipmentMilestone`. Shippers can confirm (`CONFIRMED`) or dispute (`DISPUTED`) the delivery.
- **Freight Settlement & Commission Calculation**: `SettlementService` computes platform commission (`gross_freight - platform_commission = transporter_net_payable`) using `Decimal` precision. Configurable commission rate (default 5%) stored on each settlement.
- **Payment Provider Abstraction & Idempotency**: Payment provider logic isolated via `PaymentProvider` interface and `MockPaymentProvider` implementation. `POST /api/v1/payments/initiate/` enforces unique `idempotency_key` preventing duplicate transactions.
- **Offline-First Synchronization & Incident Reporting**: Synchronizes client-queued events in isolated savepoints. Enforces atomic idempotency via PostgreSQL unique constraints on `client_event_id`. Captures driver incident reports (`ACCIDENT`, `CHECKPOINT_DELAY`, `ROAD_PROBLEM`, `SECURITY_INCIDENT`, etc.) linked to shipments.
- **Route Optimization, Haversine Distance & Fuel Analytics**: Computes great-circle distance via Haversine formula in km. Sums ordered waypoint distances, calculates travel duration based on configurable average speed (default 50 km/h), calculates fuel consumption (km/L) and fuel costs (ETB). Recalculates routes without destroying historical audit history, detecting route deviations (`ON_ROUTE` vs `DEVIATED`).
- **AI Predictive Logistics & Advisory Intelligence**: Predicts ETA delays, shipment risk, route risk, fuel costs, incident probabilities, and transparent weighted operational risk (ETA 30%, Incident 25%, Route 20%, Fuel 15%, Deviation 10%). All predictions are strictly advisory and NEVER mutate business state. Handles insufficient data safely (`prediction_available: false`).
- **Dynamic Freight Pricing Engine & Decision Support**: Calculates recommended, minimum, and maximum freight prices in ETB based on route distance, fuel analytics, operational risk, deviation premiums, and demand/supply market pressure (`LOW`, `NORMAL`, `HIGH`). All pricing outputs are strictly decision-support recommendations and NEVER automatically mutate existing shipment, bid, invoice, or settlement values.

---

## Local Development Setup

### 1. Prerequisites
Ensure the following services are installed and running locally on your Windows machine:
- **Python**: 3.13
- **Pipenv**: Installed in Python 3.13 environment
- **PostgreSQL**: Running on `localhost:5432` with database `tradeflow` created
- **Redis**: Running on `localhost:6379`

### 2. Environment Configuration
Copy `.env.example` to `.env` and set your local PostgreSQL credentials:

```bash
# Set your local PostgreSQL password in .env
DB_PASSWORD=your_actual_postgres_password
```

### 3. Install Dependencies
```bash
pipenv install --dev
```

### 4. Run Database Migrations
```bash
pipenv run python manage.py migrate
```

### 5. Verify System Checks & Run Full Test Suite (133/133 Passed 100%)
```bash
pipenv run python manage.py check
pipenv run pytest
```

### 6. Start the Backend Development Server
```bash
pipenv run python manage.py runserver 8000
```

### 7. Interactive API Documentation (OpenAPI / Swagger)
Once the server is running, visit:
- **Swagger UI**: `http://127.0.0.1:8000/api/docs/`
- **OpenAPI Schema**: `http://127.0.0.1:8000/api/schema/`
