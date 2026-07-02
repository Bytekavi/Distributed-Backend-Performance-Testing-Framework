output "worker_instance_ids" {
  description = "EC2 instance IDs for all load-generator nodes."
  value       = aws_instance.worker[*].id
}

output "worker_private_ips" {
  description = "Private IP addresses for all load-generator nodes."
  value       = aws_instance.worker[*].private_ip
}

output "worker_security_group_id" {
  description = "Security group attached to worker nodes."
  value       = aws_security_group.worker.id
}

