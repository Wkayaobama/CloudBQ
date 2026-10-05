Here is the step-by-step plan for the **Compute Engine VM deployment** detailed in your source:

---

### **Phase 1: Google Cloud Project Setup**

1. **Google Cloud Account**: Log into Google Cloud and set up a payment profile with a credit/debit card to activate free tier access[3].
2. **Create a Project**: Create a new Google Cloud project (e.g., `n8n project`)[4].
3. **Enable API**: Search for and enable the **Compute Engine API**[4].

---

### **Phase 2: Provisioning the Free Tier VM**

1. **Create VM Instance**: Navigate to **Compute Engine &gt; VM instances** and click **Create Instance**[2]. Select the following free-tier settings[2]:
  * **Name**: e.g., `n8n-vm-01`[2]
  * **Region**: Choose a supported free-tier region (e.g., `us-central1`)[2]
  * **Machine Type**: **e2-micro** (1 shared CPU, 1 GB RAM)[2][5]
  * **Operating System**: **Ubuntu** (latest version)[5][6]
  * **Boot Disk**: Set disk type to **Standard persistent disk** with a size of **30 GB**[5][6]
  * **Firewall**: Check the boxes to **Allow HTTP traffic** and **Allow HTTPS traffic**[6]

---

### **Phase 3: Domain &amp; DNS Configuration**

1. **Assign DNS A Record**: Copy the VM's external IP address from the GCP console[6]. In your domain registrar (e.g., GoDaddy), create an **A Record** pointing your domain or subdomain (e.g., `n8n.yourdomain.com`) to the VM's external IP address[6][7].
2. **DNS Propagation**: Wait 15–30 minutes for the DNS record to propagate[6][7].

---

### **Phase 4: VM Configuration &amp; Docker Installation**

1. **SSH Connection**: Click **SSH** next to your VM instance in Google Cloud to open a browser console window[7].
2. **Install Docker**: Run system update commands (`sudo apt update &amp;&amp; sudo apt upgrade`), then install **Docker** and **Docker Compose**[8].

---

### **Phase 5: n8n Setup via Docker Compose**

1. **Environment File (** **.env** **)**: Create a project folder (e.g., `n8n-compose`) and use `nano` to create an `.env` file containing your domain name, time zone, and email address[9][10].
2. **Storage Directory**: Create a `local_files` directory inside the project folder to persist workflow data[10].
3. **Docker Compose File**: Create a `docker-compose.yml` file in the same directory[10].
4. **Launch Application**: Start the stack in detached mode using `sudo docker compose up -d`[11].
5. **Account Creation**: Access your domain via HTTPS in your web browser and complete the initial n8n admin user setup[11][12].

---

If you specifically prefer to deploy n8n as a serverless container on **Google Cloud Run** rather than a VM, let me know and I can perform web research to fetch a step-by-step Cloud Run deployment guide for you.